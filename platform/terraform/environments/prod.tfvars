# Prod: on-demand capacity across three AZs with private subnets behind NAT.
# Not applied anywhere yet -- see docs/IAC.md before standing it up.
aws_region   = "us-east-1"
environment  = "prod"
cluster_name = "otterworks-prod"

cluster_version = "1.34"

vpc_cidr           = "10.2.0.0/16"
az_count           = 3
enable_nat_gateway = true

node_instance_types = ["m6i.xlarge", "m6a.xlarge", "m5.xlarge"]
node_capacity_type  = "ON_DEMAND"
node_desired_size   = 3
node_min_size       = 3
node_max_size       = 9

ecr_prefix = "otterworks/"
# Set to true when prod moves to its own AWS account.
create_ecr_repositories = false
