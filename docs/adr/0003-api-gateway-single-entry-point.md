# ADR-0003: Go API gateway as the single north-south entry point

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

Clients (web-app, admin-dashboard, mobile/desktop shells) need one origin; backends should not each
implement JWT validation, CORS, rate limiting and resilience.

## Decision

All client traffic goes through `services/api-gateway` (Go, chi). It validates JWTs, applies CORS,
request IDs, per-IP rate limiting (`RATE_LIMIT_RPS`) and a circuit breaker per route prefix, then
reverse-proxies `/api/v1/<prefix>/*` to the owning service per `ServiceRoutes` in
`internal/config/config.go`. Public paths (login/register/refresh, health) bypass JWT validation.

## Consequences

- New backend routes are only reachable after a prefix is added to `ServiceRoutes`.
- Backends trust gateway-injected identity (ADR-0004) and must not be exposed directly.
- `shared/openapi/api-gateway.yaml` documents the prefix map; per-service specs hold payloads.
