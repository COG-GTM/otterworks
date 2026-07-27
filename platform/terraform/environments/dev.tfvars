aws_region   = "us-east-1"
environment  = "dev"
cluster_name = "otterworks-dev"

# MUST stay within EKS standard support. Extended support costs $0.60/hr against
# a standard rate of $0.10/hr -- a $360/month penalty that buys nothing, which
# is exactly what running 1.32 past its window was costing. 1.34 holds standard
# support until 2026-12-02; schedule the next bump before then.
cluster_version = "1.34"

vpc_cidr           = "10.0.0.0/16"
az_count           = 2
enable_nat_gateway = false

# Node sizing for a multi-tenant workshop cluster. Tenants are scaled to zero
# when idle (see demo-platform/reaper/idle-suspend.sh), so capacity should track
# the handful of tenants that are actually awake rather than the number
# provisioned. Fewer, larger nodes bin-pack many small tenant pods far better
# than many small nodes, and SPOT keeps the rate ~70% below on-demand.
#
# max_size 4 was a hard ceiling that two tenants already hit. It is raised to
# cover ~100 provisioned tenants at realistic concurrency; the autoscaler only
# grows the group when pods are actually pending.
node_instance_types = ["m6a.xlarge", "m6i.xlarge", "m5.xlarge", "t3.xlarge"]
node_capacity_type  = "SPOT"
node_desired_size   = 2
node_min_size       = 1
node_max_size       = 20

ecr_prefix = "otterworks/"
