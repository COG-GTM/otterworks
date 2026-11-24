# Baseline

Measured on 2026-11-24 with `tests/latency/run.sh` (defaults: 10 req/s per endpoint,
5s warmup + 30s measured, one endpoint at a time) against the local docker compose
stack on one 8 vCPU / 31 GB Linux VM. The audit table held about 1.1k events.
Raw k6 output is in the JSON files beside this one.

| Endpoint | p50 ms | p95 ms | p99 ms | p95 budget 100 ms |
|---|---|---|---|---|
| audit GET /api/v1/audit/events?user_id | 72.6 | 447.5 | 642.0 | over |
| audit GET /api/v1/audit/reports/user/{id} | 58.3 | 384.9 | 626.5 | over |
| auth POST /api/v1/auth/login | 254.0 | 261.2 | 272.7 | over |
| audit GET /api/v1/audit/resources/{id}/history | 36.4 | 176.6 | 390.3 | over |
| gateway POST /api/v1/audit/events (proxied) | 8.7 | 20.0 | 31.4 | ok |
| audit POST /api/v1/audit/events | 6.6 | 11.0 | 19.3 | ok |
| audit GET /api/v1/audit/events/{id} | 4.6 | 7.3 | 9.5 | ok |
| gateway GET /api/v1/auth/profile (proxied) | 3.2 | 6.0 | 9.6 | ok |
| auth GET /api/v1/auth/profile | 3.1 | 4.3 | 5.3 | ok |
| auth PUT /api/v1/auth/profile | 2.8 | 4.1 | 7.5 | ok |
| gateway GET /health | 0.5 | 0.9 | 1.0 | ok |

The three slow audit reads scan the whole DynamoDB table, so their latency grows
with the number of stored events; compare runs at a similar table size.
