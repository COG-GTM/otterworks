# ADR-0006: Namespace-per-tenant demo isolation on a shared EKS cluster

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

Many attendees need "their own OtterWorks" concurrently, cheaply, with injectable bugs that must
not leak between demos.

## Decision

Each tenant is a Kubernetes namespace `otterworks-<ID>` on the shared `otterworks-dev` EKS cluster,
stamped by `scripts/deploy-tenant.sh` with Helm. Per tenant: all services (or the `core` profile),
dedicated Redis and MeiliSearch, a dedicated `otterworks_<ID>` database on the shared RDS instance,
ResourceQuota/LimitRange, and a NetworkPolicy denying cross-tenant traffic. Shared: cluster/node
group, the single ingress-nginx NLB, RDS instance, S3 buckets and DynamoDB tables (Tier-A logical
prefixing). SNS/SQS are disabled for tenants. TTL labels plus the reaper and idle-suspend control cost.

## Consequences

- Isolation is logical (Tier A) by default; physical isolation (Tier B) is opt-in.
- Only the shared ingress controller may be a `LoadBalancer` Service.
- Changes to shared resources need explicit sign-off (AGENTS.md).

## References

`docs/MULTI-TENANT-DEMO-PLAN.md`, `docs/MULTI-TENANT-RUNBOOK.md`, `AGENTS.md`.
