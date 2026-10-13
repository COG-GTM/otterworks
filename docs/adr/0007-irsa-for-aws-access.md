# ADR-0007: IRSA for pod-level AWS credentials

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

file, document, audit, search, notification and analytics call S3, DynamoDB, SNS and SQS. Static
access keys in Secrets would be long-lived and shared.

## Decision

Services obtain AWS credentials through IAM Roles for Service Accounts (IRSA): Terraform creates one
IAM role per service with least-privilege policies and an OIDC trust on the EKS cluster; the Helm
chart annotates each ServiceAccount with its role ARN. The trust uses a wildcard over
`otterworks-*` namespaces so every tenant reuses the same roles.

## Consequences

- No static AWS keys in cluster Secrets; credentials rotate automatically.
- Roles are shared across tenants, so tenant isolation for AWS data relies on key/partition
  prefixes (ADR-0006) rather than IAM; per-tenant scoped roles are the Tier-B option.
- IAM/IRSA changes affect every tenant and need sign-off (AGENTS.md).
