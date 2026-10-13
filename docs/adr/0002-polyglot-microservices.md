# ADR-0002: Polyglot microservices, one language per service

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

OtterWorks is a reference/demo platform for modernization work across many technology stacks.
It needs realistic services in the languages enterprises actually run.

## Decision

Each backend capability is an independently deployable service with its own language, build and
data store: Go (api-gateway), Java/Spring Boot (auth, report), Rust/Actix (file), Python/FastAPI
(document, billing), Python/Flask (search), TypeScript/Node (collab), Kotlin/Ktor (notification),
Scala/Akka HTTP (analytics), Ruby on Rails (admin), C#/ASP.NET (audit). Services communicate over
HTTP behind the gateway and via asynchronous events (ADR-0005). Contracts live in `shared/openapi/`
(HTTP), `shared/events/schemas/` (events) and `shared/proto/` (typed internal contracts).

## Consequences

- Every service has its own CI job, toolchain and coverage gate (`.github/workflows/ci.yml`,
  `docs/testing/coverage-thresholds.md`).
- Cross-service changes must be expressed as contract changes first; the contract lint workflows
  (`contracts.yml`) are the guardrail.
- Operational cost (13 images, many runtimes) is accepted; tenants can deploy a 5-service `core`
  profile to limit it.

## References

`ARCHITECTURE.md`, `services/*`, `docker-compose.yml`.
