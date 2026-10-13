# ADR-0004: Gateway strips and re-injects identity headers from the JWT

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

Backends (file, document, report, ...) identify the caller via `X-User-ID` / `X-User-Email`
instead of re-validating JWTs. If a client could send those headers itself it could impersonate
any user.

## Decision

The gateway's proxy director (`internal/proxy/router.go`) always deletes client-supplied
`X-User-ID` and `X-User-Email`, and only sets them from claims of a JWT validated by
`internal/middleware/jwt.go` (`sub`, falling back to `user_id`, and `email`).

## Consequences

- Backends may trust these headers only when reached through the gateway; direct exposure of a
  backend is a security bug (NetworkPolicy and ClusterIP-only Services enforce this in-cluster).
- Some services keep a fallback (e.g. file-service accepts `owner_id`), which is only safe behind
  the gateway; new services should not add such fallbacks.
- Regression tests: `internal/proxy/router_test.go`.
