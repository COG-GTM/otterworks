# Staging: dev's shape with a little redundancy, for pre-prod verification.
# Not applied anywhere yet -- see docs/IAC.md before standing it up.
aws_region   = "us-east-1"
environment  = "staging"
cluster_name = "otterworks-staging"

cluster_version = "1.34"

# Non-overlapping with dev (10.0.0.0/16) so the VPCs can be peered later.
vpc_cidr           = "10.1.0.0/16"
az_count           = 2
enable_nat_gateway = true

node_instance_types = ["m6a.xlarge", "m6i.xlarge", "m5.xlarge"]
node_capacity_type  = "SPOT"
node_desired_size   = 2
node_min_size       = 1
node_max_size       = 4

ecr_prefix = "otterworks/"
# ECR repository names are not environment-scoped and dev already owns them in
# this account; staging pulls the same images.
create_ecr_repositories = false
