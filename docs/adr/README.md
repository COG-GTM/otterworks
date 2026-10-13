# Architecture Decision Records

Short, immutable records of significant architecture decisions, in the
[Michael Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

- Copy [`0000-template.md`](0000-template.md) to `NNNN-short-title.md` (next free number).
- Status is one of `Proposed`, `Accepted`, `Deprecated`, `Superseded by ADR-NNNN`.
- Never rewrite an accepted ADR's decision; supersede it with a new ADR and update the old one's status.
- Link the ADR from the PR that implements it.

ADRs 0001-0008 were written retroactively to document decisions already embodied in the code and
infrastructure; their "Date" is the date they were recorded.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-polyglot-microservices.md) | Polyglot microservices, one language per service | Accepted |
| [0003](0003-api-gateway-single-entry-point.md) | Go API gateway as the single north-south entry point | Accepted |
| [0004](0004-gateway-identity-header-stripping.md) | Gateway strips and re-injects identity headers from the JWT | Accepted |
| [0005](0005-async-events-over-sns-sqs.md) | Asynchronous cross-service events over SNS/SQS with JSON Schema contracts | Accepted |
| [0006](0006-namespace-per-tenant.md) | Namespace-per-tenant demo isolation on a shared EKS cluster | Accepted |
| [0007](0007-irsa-for-aws-access.md) | IRSA for pod-level AWS credentials | Accepted |
| [0008](0008-legacy-before-state-fixtures.md) | Keep legacy "before state" fixtures alongside modernized implementations | Accepted |
