# ADR-0005: Asynchronous cross-service events over SNS/SQS with JSON Schema contracts

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

Search indexing, notifications and audit need to react to file/document changes without coupling
producers to every consumer or blocking user requests.

## Decision

Producers (file-service, document-service, collab-service) publish domain events to SNS topics;
consumers (search, notification, audit, analytics) read from their own SQS queues. Event payloads
are defined by JSON Schemas in `shared/events/schemas/`; `shared/proto/otterworks/events/v1`
mirrors them as buf-checked messages for field stability. Locally, LocalStack provides SNS/SQS.

## Consequences

- Side effects are eventually consistent (see `tests/api/test_side_effect_flow.py`).
- Demo tenants disable SNS/SQS to avoid cross-tenant consumers (ADR-0006).
- Event field changes must stay backward compatible; `buf breaking` enforces this for the proto mirror.
