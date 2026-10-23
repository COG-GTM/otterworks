# QA audit: api-gateway

Scope: `services/api-gateway` (Go, chi). Audited the route table (`internal/config/config.go`), JWT middleware (public vs protected paths, trusted identity headers), CORS, per-IP rate limiting, Prometheus path labels, `/health`, request IDs, reverse proxy error handling and the per-route circuit breaker.

## Test pyramid

| Layer | Location | Tests | Pass | xfail / skip |
|---|---|---|---|---|
| Unit (`go test`) | `services/api-gateway/**/{config_test,main_test,*_qa_test}.go` | 59 new test funcs (+29 subtests); 87 top-level incl. existing | 52 new | 7 `t.Skip("xfail QA-GW-…")` |
| Functional (pytest via :8080) | `tests/api/test_qa_api_gateway.py` | 40 (incl. parametrized) | 36 | 4 `xfail(strict=True)` |
| E2E Playwright | `frontend/client-app/e2e/qa-api-gateway.spec.ts` | 6 | 6 | 0 |
| E2E computer use | testing agent recording (see PR comment) | 3 flows | 3 | 0 |

Commands: `cd services/api-gateway && go vet ./... && go test -race ./...`; `make test-api-flows` (or `python -m pytest tests/api/test_qa_api_gateway.py`); `cd frontend/client-app && npx playwright test e2e/qa-api-gateway.spec.ts`.

Each skipped/xfail test asserts the *correct* behaviour; most have a sibling "characterises" test asserting the current (buggy) behaviour so a fix flips both.

### What is covered

- **Routes:** every `ServiceRoutes()` prefix maps to its backend; every prefix the client app calls is routed; all prefixes become JWT-protected (`routePrefixes`); config defaults, env overrides, invalid values and `Validate()` fail-fast on empty `JWT_SECRET`.
- **JWT:** all 14 route prefixes return 401 without a token; exact public paths (`/auth/login`, `/auth/register`, `/auth/refresh`) don't leak to siblings (`/login/`, `/users`); `/health`, `/metrics`, `/socket.io` prefixes respect segment boundaries; expired, not-yet-valid, wrong-secret, `alg=none`, tampered, garbage, empty, Basic and scheme-less credentials rejected; case-insensitive `Bearer`; claims reach the context; `//`, `/./` and `/../` paths don't bypass auth.
- **Trusted identity:** client `X-User-ID` / `X-User-Email` are stripped on public routes and replaced by token claims on protected routes (incl. legacy `user_id` claim); live: user B spoofing user A's `X-User-ID` cannot read A's document.
- **CORS:** exact allow-list, preflight returns 204 with `Authorization` allowed and credentials; foreign origins get no ACAO header; 401s are readable by the app origin.
- **Rate limiting:** per-IP buckets, refill cap, 429 JSON + `Retry-After`, IPv6 keys; live 429 burst.
- **Metrics:** request counter exposed, IDs never become label values.
- **Proxy / resilience:** path, query and Authorization forwarded unchanged; unknown route -> JSON 404; upstream down -> 502 JSON without leaking the upstream address, then 503 `circuit breaker open`; breakers isolated per route; 4xx don't trip the breaker; half-open probe limit and re-open; live upstream-down check against an un-started optional backend (reports/audit/analytics).
- **E2E:** unauthenticated `/dashboard`, `/files`, `/documents` -> `/login`; garbage and expired (validly signed) tokens in localStorage are rejected via `/auth/profile` 401, cleared, and the user lands on `/login`; register -> dashboard -> files -> documents -> dashboard with 200s from the gateway.

### Computer-use run (real Chrome, core stack)

- Pass: with empty localStorage, `/dashboard`, `/files` and `/documents` each land on `/login`.
- Pass: with `not-a-jwt` in both token keys, `/files` bounces to `/login` and both keys are cleared.
- Pass: register -> Dashboard -> Files -> Documents -> Dashboard stays signed in; a new document persists across reload.
- Note (environment, not a gateway defect): the core profile doesn't run notification-service, so `/api/v1/notifications/unread-count` returns gateway 502 -> 503 `circuit breaker open`. That's the intended failure handling. The editor shows "Reconnecting..." because collab-service isn't running either.

## Findings

| ID | Severity | Location | Repro | Expected | Actual |
|---|---|---|---|---|---|
| QA-GW-01 | High | `internal/middleware/jwt.go:106-127` `validateToken` | Log in, call `GET /api/v1/documents/` with the **refresh** token as `Bearer` | 401: only `type=access` tokens authenticate API calls | 200. The `type` claim is never checked, so the long-lived refresh token (signed with the same key) works as an access token everywhere |
| QA-GW-02 | Medium | `internal/middleware/jwt.go:108` (`jwt.ParseWithClaims` without `jwt.WithExpirationRequired()`) | Sign `{"sub":…}` with no `exp` using the gateway secret, call any protected route | 401 | 200: tokens without `exp` never expire |
| QA-GW-03 | Medium | `cmd/server/main.go:69,76-77` (`chimw.RealIP` before `RateLimiter`) | Send > `RATE_LIMIT_RPS` requests/s rotating `X-Forwarded-For` | 429 after the burst | No 429: limiter keys on a client-controlled header, so rate limiting is trivially bypassed |
| QA-GW-04 | Low | `internal/middleware/metrics.go:63-87` `normalizePath` | Hit `/api/v1/folders`, `/settings`, `/templates`, `/preferences`, `/reports`, `/socket.io`; or `/api/v1/filesystem` | One label per routed prefix, segment-aware | Six routed prefixes are labelled `other`; raw prefix match labels `/api/v1/filesystem` as `/api/v1/files` |
| QA-GW-05 | Low | `cmd/server/main.go:76-88` (rate limiter registered before CORS) | Exceed the rate limit from a browser origin | 429 with `Access-Control-Allow-Origin` so the SPA can read it | 429 has no CORS headers; the browser surfaces an opaque network error |
| QA-GW-06 | Low | `internal/proxy/circuitbreaker.go:82-90` `NewCircuitBreaker` | Fail some requests, wait > `CB_INTERVAL_SECONDS`, fail more | Counts reset each interval while closed | First closed generation has zero expiry, so counts accumulate forever until the breaker trips once; stale failures can open it |

## Not tested / limitations

- **Live 503 vs 502 timing** is environment-dependent (needs an optional backend to be down); the functional test skips if all optional backends are running. Unit tests cover it deterministically.
- The expired-JWT browser variant was automated in Playwright but not repeated in the computer-use run (only the garbage token was).
- **WebSocket upgrade through `/socket.io`** not exercised end-to-end: collab-service is not in the core profile.
- **Rate-limit live tests** assume a single client at default `RATE_LIMIT_RPS=100`; set `OTTERWORKS_QA_SKIP_RATE_LIMIT=1` on shared stacks. They sleep to refill the bucket so later tests aren't throttled; running other suites concurrently against the same gateway can cause 429s.
- Forged-token functional tests use the docker-compose default secret (`OTTERWORKS_JWT_SECRET` overrides it) and skip if it doesn't match the running gateway.
- **Pre-existing failures** in `make test-api-flows` on the core profile come from other suites hitting services that aren't started (search, audit, analytics, notification, admin, collab) and `test_document_flow`; none are in this unit.
- `golangci-lint` isn't installed on the VM; `go vet` and `go test -race` (what CI runs) pass.
