# Platform latency baseline and p95 budget check

k6 load scripts for the main read and write paths of `auth-service`, `audit-service` and
`api-gateway`, plus a check (`run.sh`) that exits non-zero when any endpoint's p95 is over
its budget in `budgets.json` or its error rate is 1% or higher.

## Bring the services up

From the repo root (needs Docker and k6 v0.54+):

```bash
docker compose -f docker-compose.infra.yml -f docker-compose.yml build auth-service audit-service api-gateway
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d postgres redis localstack auth-service audit-service api-gateway
curl -fs localhost:8081/health && curl -fs localhost:8090/health && curl -fs localhost:8080/health
```

If host port 6379 (Redis) or 9090 (Prometheus) is already taken, add an override file that
sets `ports: !override []` for `redis` and `prometheus`; nothing in these scripts needs them
on the host.

## Run the check

```bash
tests/latency/run.sh                                   # all three services, all endpoints
tests/latency/run.sh auth audit                        # selected services
ENDPOINTS=auth_profile,gateway_health tests/latency/run.sh
RATE=10 DURATION_S=30 tests/latency/run.sh             # load shape (these are the defaults)
```

Each endpoint gets its own constant-arrival-rate scenario (default 10 req/s for 30 s, run one
after another so they do not compete). `audit.js` first seeds the audit table up to
`SEED_EVENTS` (default 2000) events so the query path reads a non-empty table. Per-service
JSON results go to `RESULTS_DIR` (default `tests/latency/results/`, git-ignored), and the run
ends with a slowest-first table and `PASS` or `FAIL`.

| Endpoint | Request |
|---|---|
| auth_register | `POST /api/v1/auth/register` (new user each call) |
| auth_login | `POST /api/v1/auth/login` |
| auth_profile | `GET /api/v1/auth/profile` |
| audit_record_event | `POST /api/v1/audit/events` |
| audit_query_events | `GET /api/v1/audit/events?user_id=…&size=20` |
| gateway_health | `GET /health` on the gateway |
| gateway_profile | `GET /api/v1/auth/profile` through the gateway |
| gateway_audit_record | `POST /api/v1/audit/events` through the gateway |

## Baseline (2026-11-24, local Docker Compose, 10 req/s for 30 s per endpoint)

Measured on one Devin VM with all containers on the same host, so absolute numbers are
local-only; compare runs on the same machine. Two full runs, slowest first by run 1 p95:

| Endpoint | Run 1 p50 / p95 / p99 ms | Run 2 p50 / p95 / p99 ms | Proposed p95 budget | Status |
|---|---|---|---|---|
| auth_register | 251.6 / 278.6 / 296.9 | 252.5 / 295.1 / 359.2 | 100 ms | **over** |
| auth_login | 250.8 / 272.7 / 278.1 | 257.4 / 318.0 / 366.9 | 100 ms | **over** |
| audit_query_events | 17.2 / 24.9 / 35.7 | 21.4 / 35.9 / 53.4 | 50 ms | ok |
| gateway_audit_record | 7.8 / 13.2 / 24.9 | 7.4 / 10.9 / 15.4 | 25 ms | ok |
| audit_record_event | 7.1 / 10.4 / 17.2 | 6.7 / 8.6 / 13.4 | 25 ms | ok |
| auth_profile | 2.9 / 7.8 / 15.6 | 1.7 / 2.7 / 3.6 | 25 ms | ok |
| gateway_profile | 3.4 / 6.5 / 10.3 | 2.7 / 6.3 / 10.6 | 25 ms | ok |
| gateway_health | 0.5 / 0.8 / 1.8 | 0.6 / 0.9 / 1.2 | 10 ms | ok |

Error rate was 0% for every endpoint in both runs. The audit table held 2052 events before
run 1 and 2654 before run 2 (each full run adds about 600).

Budgets are round numbers every healthy endpoint already meets with at least 1.4x headroom
on its worst p95: 10 ms for the gateway health check, 25 ms for single-row reads and writes,
50 ms for the audit query, and 100 ms for register and login, which they miss by about 3x.

### Check runs

- Run 2 (`tests/latency/run.sh`, budgets above): `FAIL`, exit 1, on `auth_register` and
  `auth_login` only.
- Run 3, healthy endpoints only
  (`ENDPOINTS=auth_profile,audit_record_event,audit_query_events,gateway_health,gateway_profile,gateway_audit_record tests/latency/run.sh`):
  `PASS`, exit 0. p95: audit_query_events 29.5, audit_record_event 10.8, gateway_audit_record 8.4,
  auth_profile 3.0, gateway_profile 3.0, gateway_health 1.0 ms.

### Noise and caveats

- Register and login moved by up to 45 ms p95 between runs; the faster endpoints moved by a
  few ms (auth_profile p95 7.8 vs 2.7 ms). A 5 req/s, 5 s smoke run earlier showed register
  at 425 ms p95, so treat the first run after a cold start as warm-up.
- The audit query's latency depends on table size, which grows with every run. With the
  table seeded to 10,000 events (`SEED_EVENTS=10000 ENDPOINTS=audit_query_events tests/latency/run.sh audit`)
  it measured p50 157.6 / p95 285.9 / p99 474.2 ms and failed its 50 ms budget.

## Slowest endpoints and likely causes

1. **auth_register** (slowest at the default seed): `SecurityConfig` uses
   `new BCryptPasswordEncoder(12)`, and register hashes the password on every call.
2. **auth_login**: the same cost-12 BCrypt `matches` on every login, plus a `lastLoginAt`
   write in the same transaction. Profile reads on the same service take about 3 ms, so the
   time is most likely in the hash, not the database or the JVM. Not yet confirmed by
   measuring a lower cost.
3. **audit_query_events**: `DynamoDbAuditRepository.QueryEventsAsync` runs a full-table
   `Scan` (the user filter is a `FilterExpression`, applied after every item is read),
   follows every `LastEvaluatedKey` page, sorts all matches in memory and only then applies
   `Skip/Take`. Cost grows with table size: 25–36 ms p95 at 2–3k events, 286 ms at 10k.
4. **gateway_audit_record**: one DynamoDB `PutItem` (on LocalStack here) plus the gateway hop;
   the gateway adds about 2–3 ms over the direct `audit_record_event` call (JWT check,
   gzip, rate limiter, default reverse-proxy transport). No problem found at this load.
