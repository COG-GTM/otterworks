# ------------------------------------------------------------------------------
# OtterWorks Platform - VPC Module
# Standalone VPC with public and private subnets for EKS
# ------------------------------------------------------------------------------

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  # The /20 pod subnets take blocks 1..az_count of the VPC's /20 grid; block 6
  # is where the /24 public subnets already sit (x.x.100.0/24), so past five AZs
  # the two would overlap and the apply would fail on a CIDR conflict.
  pod_subnet_az_limit = 5

  common_tags = {
    Module  = "vpc"
    Project = var.project
  }

  # Karpenter's EC2NodeClass finds where to launch nodes by this tag, so it goes
  # on the subnets nodes actually belong in -- private when there is a NAT
  # gateway to reach the internet through, public otherwise, matching what the
  # root module hands the node group. Tagging both would let Karpenter place a
  # node in a private subnet with no route out, where it would fail to pull
  # images or register with the cluster.
  #
  # It lives in the subnet's own tag set rather than in a separate aws_ec2_tag
  # resource because aws_subnet owns the whole set and strips anything else on
  # the next apply.
  karpenter_discovery = { "karpenter.sh/discovery" = var.cluster_name }

  karpenter_discovery_public  = var.enable_nat_gateway ? {} : local.karpenter_discovery
  karpenter_discovery_private = var.enable_nat_gateway ? local.karpenter_discovery : {}
}

# --- VPC ---

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}"
  })
}

# --- Internet Gateway ---

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}"
  })
}

# --- Public Subnets ---

resource "aws_subnet" "public" { # nosemgrep: terraform.aws.security.aws-subnet-has-public-ip-address.aws-subnet-has-public-ip-address
  count = var.az_count

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 100 + count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = merge(local.common_tags, local.karpenter_discovery_public, {
    Name                                        = "${var.project}-public-${local.azs[count.index]}"
    "kubernetes.io/role/elb"                    = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  })
}

# --- Private Subnets ---

resource "aws_subnet" "private" {
  count = var.az_count

  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 1)
  availability_zone = local.azs[count.index]

  tags = merge(local.common_tags, local.karpenter_discovery_private, {
    Name                                        = "${var.project}-private-${local.azs[count.index]}"
    "kubernetes.io/role/internal-elb"           = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  })
}

# --- Pod Subnets ---

# The /24s above hold ~250 addresses each, and the VPC CNI gives every pod a
# real subnet address: two AZs is ~500 pods, which a few dozen tenants exhaust
# while compute is still half idle. Persistent tenants make that the binding
# constraint rather than a transient one, because they never scale to zero.
#
# These are additional node subnets, /20 (4091 usable) each, carrying the same
# discovery tag so Karpenter launches into whichever candidate has the most free
# addresses. They are additive: the existing subnets keep their CIDRs, so no
# subnet is replaced and no running node is disturbed by an apply.
#
# Deliberately not tagged `kubernetes.io/role/elb`. That is what keeps the shared
# NLB where it is, and it is a preference rather than an exclusion: the in-tree
# AWS provider (there is no aws-load-balancer-controller here -- ingress-nginx
# asks for an NLB with the legacy `aws-load-balancer-type` annotation) considers
# every subnet in the VPC that is either tagged for this cluster or tagged for no
# cluster at all, and with `enable_nat_gateway = false` these sit on the public
# route table, so they read as public and land in that candidate set. It then
# keeps one subnet per AZ, preferring the one carrying the role tag -- which is
# the original public subnet in each AZ, in every AZ, since both sets are
# `az_count` wide. Dropping the cluster tag here would not narrow the set (an
# untagged subnet is a candidate too); the role tag is the lever.
resource "aws_subnet" "pods" { # nosemgrep: terraform.aws.security.aws-subnet-has-public-ip-address.aws-subnet-has-public-ip-address
  count = var.az_count

  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index + 1)
  availability_zone = local.azs[count.index]

  # Nodes land here, so egress has to work the same way it does in whichever
  # subnet they use today: a public address when there is no NAT gateway.
  map_public_ip_on_launch = !var.enable_nat_gateway

  tags = merge(local.common_tags, local.karpenter_discovery, {
    Name                                        = "${var.project}-pods-${local.azs[count.index]}"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  })

  lifecycle {
    precondition {
      condition     = var.az_count <= local.pod_subnet_az_limit
      error_message = "az_count > ${local.pod_subnet_az_limit} overlaps the public subnets; renumber the pod subnets before widening the VPC."
    }
    # Four bits of subnetting is a /20 only from a /16, which is what the docs
    # and the capacity numbers assume. From anything narrower the same expression
    # quietly yields smaller subnets -- a /18 VPC gives /22s, ~1,000 pods per AZ
    # instead of ~4,000 -- and the roster's preflight would be sized against
    # capacity that does not exist.
    precondition {
      condition     = tonumber(split("/", var.vpc_cidr)[1]) <= 16
      error_message = "vpc_cidr must be /16 or larger for the pod subnets to be the documented /20s (got ${var.vpc_cidr})."
    }
  }
}

# --- NAT Gateway (single, cost-optimized for dev) ---

resource "aws_eip" "nat" {
  count  = var.enable_nat_gateway ? 1 : 0
  domain = "vpc"

  tags = merge(local.common_tags, {
    Name = "${var.project}-nat-${var.environment}"
  })
}

resource "aws_nat_gateway" "main" {
  count = var.enable_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags = merge(local.common_tags, {
    Name = "${var.project}-nat-${var.environment}"
  })

  depends_on = [aws_internet_gateway.main]
}

# --- Route Tables ---

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = merge(local.common_tags, {
    Name = "${var.project}-public-${var.environment}"
  })
}

resource "aws_route_table_association" "public" {
  count = var.az_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  dynamic "route" {
    for_each = var.enable_nat_gateway ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.main[0].id
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.project}-private-${var.environment}"
  })
}

resource "aws_route_table_association" "private" {
  count = var.az_count

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# Same route table the nodes already use: private (via NAT) when there is a NAT
# gateway, public (via the IGW) otherwise. A pod subnet on the private table
# with no NAT would give nodes no route out.
resource "aws_route_table_association" "pods" {
  count = var.az_count

  subnet_id      = aws_subnet.pods[count.index].id
  route_table_id = var.enable_nat_gateway ? aws_route_table.private.id : aws_route_table.public.id
}
