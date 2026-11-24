# Platform latency

Repeatable load scripts for the platform services, with a p95 budget check.

| Script | Service | Endpoints (read and write paths) |
|---|---|---|
| `auth.js` | auth-service, `:8081` | `POST /login`, `GET /profile`, `PUT /profile` |
| `audit.js` | audit-service, `:8090` | `POST /events`, `GET /events?user_id`, `GET /events/{id}`, `GET /resources/{id}/history`, `GET /reports/user/{id}` |
| `gateway.js` | api-gateway, `:8080` | `GET /health`, proxied `GET /api/v1/auth/profile`, proxied `POST /api/v1/audit/events` |

## Run

Needs Docker and [k6](https://k6.io).

```bash
docker compose -f docker-compose.infra.yml -f docker-compose.yml build auth-service audit-service api-gateway
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d postgres redis localstack
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d --no-deps auth-service audit-service api-gateway
tests/latency/run.sh                 # all three; or: tests/latency/run.sh audit
```

Each script writes `results/<service>.json` with p50/p95/p99 per endpoint, then
`check_budget.py` compares p95 to `budgets.json` and exits 1 if any endpoint is over.

Knobs: `RATE` (req/s per endpoint, default 10), `DURATION` (30s), `WARMUP` (5s),
`SEED_EVENTS` (audit events seeded before the run, 500), `AUTH_URL`, `AUDIT_URL`,
`GATEWAY_URL`, `OUT_DIR`, and `CHECK_ARGS` (extra flags for the check, e.g.
`CHECK_ARGS="--exclude auth_login"`).

Notes:
- `--no-deps` keeps compose from starting services these scripts don't use.
- The gateway rate-limits each client IP to `RATE_LIMIT_RPS` (100 by default); endpoints run
  one at a time, so keep `RATE` under that.
- The audit read paths scan the whole table, so they slow down as events accumulate across
  runs. Compare runs at a similar table size, or reset LocalStack's volume first.

## Budgets

`budgets.json` sets `default_p95_ms` for every endpoint, with optional per-endpoint
`p95_ms` overrides. p95 counts successful responses only; an endpoint fails as `ERRORS` when
its error rate is over `max_error_rate` (1%), and as `NO DATA` when it has no successful sample.
An entry with a `"waiver"` (an approved release exception) is reported
as `WAIVED` and does not fail the check. Baseline numbers are in `baseline/`.

```bash
python3 tests/latency/check_budget.py tests/latency/results/*.json
python3 -m unittest discover -s tests/latency -p 'test_*.py'
```
