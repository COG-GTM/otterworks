# commission-service — Insurance Commission Pay, extracted from PL/SQL

The Commission Pay business logic used to live only in Oracle PL/SQL
(`../db/oltp/03_commission_pkg.sql`, `../db/olap/02_etl_pkg.sql`). This service moves it
into application code. **The Oracle fixture in `../db/` is the frozen before-state and is
not modified**; it keeps running beside this service through `docker-compose.insurance.yml`
and is the reference the parity harness records against.

```
app/domain/      pure business rules (no SQL, no HTTP): rates, splits, calculation, etl,
                 oracle_compat (Oracle NUMBER rounding/TO_CHAR), errors (legacy ORA codes)
app/repository.py  PostgreSQL adapters for the domain ports, bound to one tenant
app/db.py        tenant-bound transactions, migrations, per-tenant seed/reset
app/security.py  JWT validation, roles, tenant claim
app/main.py      FastAPI edge
db/migrations/   PostgreSQL schema (tenant_id on every table + forced RLS)
db/seed/         northwind-mutual (row-for-row copy of the Oracle seed), contoso-life (isolation tenant)
db/init/         creates the non-superuser app role for the composed Postgres
```

## Before → after mapping

All paths are under `/api/v1/commission`. Business errors keep the legacy code:
`{"error": {"code": "...", "legacy_ora_code": -20006, "message": "<same text as RAISE_APPLICATION_ERROR>"}}`.

| PL/SQL (before) | Domain function (after) | Endpoint | Role |
|---|---|---|---|
| `commission_pkg.upsert_commission_rate` | `rates.upsert_commission_rate` | `PUT /rates` | rate admin |
| `commission_pkg.end_commission_rate` | `rates.end_commission_rate` | `POST /rates/end` | rate admin |
| `commission_pkg.resolve_rate` | `rates.resolve_rate` | `GET /rates/resolve?product_code&agent_id&as_of` | viewer |
| `SELECT … FROM commission_rates` | repository `rates_for_product` | `GET /rates?product_code` | viewer |
| `commission_pkg.set_commission_splits` | `splits.set_commission_splits` | `PUT /policies/{id}/splits` | manager |
| `SELECT … FROM commission_splits` | repository `list_splits` | `GET /policies/{id}/splits` | viewer |
| `commission_pkg.calculate_policy_commission` | `calculation.calculate_policy_commission` | `POST /policies/{id}/calculations` | manager |
| `commission_ledger` (payout statement) | repository `list_ledger` | `GET /ledger?policy_id&period_month` | viewer |
| `commission_pkg.log_action` / `rate_audit_log` | `repo.log_action` (every mutation) | `GET /audit` | rate admin |
| `dw_etl_pkg.load_commission_facts` | `etl.load_commission_facts` | `POST /etl/loads` | rate admin |
| `fact_commission` + dims | repository `list_facts` | `GET /facts?period_month` | viewer |
| `MV_AGENT_COMMISSION_SUMMARY` | `etl.summarize` | `GET /summary?period_month` | viewer |

Rule-by-rule detail (statement, PL/SQL line range, scenarios, unit test) is in
`../parity/rules/*.rules.yaml`; every rule id there has a `@pytest.mark.rule("…")` test.

### Intentional differences from Oracle

| Rule | Oracle | Service | Why |
|---|---|---|---|
| INS-RATE-009 | `UX_RATES_OPEN` indexes closed rows as `(product, agent, NULL)`, so the second supersede of a key fails with ORA-00001 | Partial unique index on open rows only; full history kept | Legacy defect; scenario `INS-RATES-017` |
| INS-CALC-009 | `TO_DATE('2025-6','YYYY-MM')` succeeds and writes ledger rows under a non-canonical key `2025-6` | Requires `YYYY-MM`; returns `-1861` | Non-canonical keys never reconcile with `2025-06`; scenario `INS-CALC-010` |
| INS-ETL-005 | Summary is a `REFRESH ON DEMAND` materialized view | Computed from facts on read | No stale-refresh state to manage; parity refreshes the MV before reading |
| INS-RATE-010 | Backdated insert fails with ORA-00001 on the index | Same ORA-00001 code, clean `DUPLICATE_OPEN_RATE` error | Same outcome, explicit check |

Both rate and split values are validated *raw* and stored rounded half-up to cents, exactly as
Oracle `NUMBER(5,2)` columns do (`12.345` passes validation, stores `12.35`, audit keeps `12.345`).

## Security model

* **Authentication.** Every endpoint except `/health` needs `Authorization: Bearer <jwt>`.
  Tokens are validated in-process with the shared OtterWorks `JWT_SECRET` (the key
  auth-service signs with; HS256/HS384/HS512 only, `none` and asymmetric algorithms
  rejected). `exp` is required, `type` must be `access` when present, subject comes from
  `sub` (auth-service) or `user_id` (gateway claims). Optional `COMMISSION_SVC_JWT_ISSUER` /
  `COMMISSION_SVC_JWT_AUDIENCE` are enforced when set. Identity headers such as `X-User-ID`
  are never trusted — the gateway does not forward roles or tenant, so the service
  re-validates the token itself.
* **Authorization.** Roles from the `roles` claim (`ROLE_` prefix accepted):

  | Capability | Roles |
  |---|---|
  | read rates, splits, ledger, facts, summary | `COMMISSION_VIEWER`, `COMMISSION_MANAGER`, `COMMISSION_ADMIN`, `ADMIN`, `OWNER` |
  | set splits, run calculations | `COMMISSION_MANAGER`, `COMMISSION_ADMIN`, `ADMIN`, `OWNER` |
  | change rates, read audit, run ETL | `COMMISSION_ADMIN`, `ADMIN`, `OWNER` |

  A plain `USER` token gets 403.
* **Tenant scoping.** The tenant comes only from the signed token (claim `tenant_id`,
  configurable via `COMMISSION_SVC_TENANT_CLAIM`); a token without it gets 403. Every
  table carries `tenant_id`. Each request runs in one transaction that sets
  `app.tenant_id` (`set_config(..., true)`), every repository query also filters on
  `tenant_id`, and PostgreSQL **forced** row-level security (`USING`/`WITH CHECK
  tenant_id = current_setting('app.tenant_id')`) backs that up, so a missed filter still
  cannot read or write another tenant. The service must connect as a non-superuser,
  non-`BYPASSRLS` role (`db/init/01_app_role.sh`). Natural ids (policy 4, agent 1)
  overlap between tenants on purpose to prove isolation.
* **Secrets.** No credentials in code or images. `JWT_SECRET` (≥ 32 bytes) and
  `COMMISSION_SVC_DATABASE_URL` are required environment variables — the service refuses
  to start without them. In Kubernetes they would come from the existing secret wiring;
  locally `make commission-up` generates throwaway random values into the gitignored
  `../parity/.local.env`. `POST /internal/reset` (used by parity) answers 404 unless
  `COMMISSION_SVC_ENABLE_RESET=true` **and** the caller's tenant is listed in
  `COMMISSION_SVC_RESET_TENANTS`; it also needs the dedicated `COMMISSION_PARITY_RESET` role
  (tenant `ADMIN` is not enough) and only resets the caller's own tenant.
- Concurrency: rate writers take a transaction advisory lock per tenant/product/agent scope;
  split replacement and recalculation lock the policy row, so concurrent requests serialise.

## Running it

```bash
make commission-test                   # ruff, ruff format, mypy, unit tests (no DB)
make commission-up NS=dev              # service + its Postgres on per-NS ports (printed)
make commission-integration NS=dev     # HTTP, role and tenant-isolation tests against that Postgres
make commission-rules-gate             # rule ledger + transcript freshness
make commission-parity NS=dev          # replay Oracle transcripts against the service
make commission-down NS=dev
```

Recording (needs the Oracle fixture: `make insurance-up NS=dev`):
`make commission-record NS=dev`. Transcripts are immutable; re-recording needs
`ALLOW_RERECORD=1 RERECORD_REASON="..."`. Transcripts carry SHA-256 fingerprints of the
PL/SQL packages and the fixture schema/seed, and replay fails if either changed.

See `../parity/README.md` for the harness.
