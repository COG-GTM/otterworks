# Billing Service

This FastAPI service is the extraction target for the plans module. It owns a
separate Postgres `billing_svc` schema, keeps the HTTP layer thin, and places
plans behavior in a plain-Python domain layer.

## Development

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8097
uv run pytest
uv run ruff check app scripts tests
```

The deterministic target seed is generated from
`services/legacy-billing/db/seed.sql`:

```bash
python scripts/generate_seed.py
```

The generated-seed test prevents the target fixture from drifting from the
legacy before-state. `POST /internal/reset` applies the migration, truncates
the `billing_svc` schema, and reseeds it so the parity harness can isolate
every scenario.

## Authentication and tenant scoping

Every `/api/*` endpoint requires `Authorization: Bearer <access token>`: an
HMAC platform access token (HS256/HS384/HS512, as auth-service's JJWT signer
picks by secret length; `type: access`, `sub`, finite `exp`) signed with
`BILLING_SVC_JWT_SECRET` (the platform `JWT_SECRET`, at least 32 characters).
If the secret is unset or too short, the endpoints fail closed with 503.

- `GET /api/plans` accepts any valid access token.
- `GET /api/tenants/{tenant_id}/entitlement` and
  `POST /api/tenants/{tenant_id}/plan-change` additionally require the token's
  `tenant_id` claim to equal the path tenant, or a role listed in
  `BILLING_SVC_ADMIN_ROLES` (default `["ADMIN"]`). Anything else is 403 and
  never reaches the database. auth-service does not issue `tenant_id` today, so
  until the platform has a tenant-membership source only admin tokens (and
  service tokens minted with a `tenant_id`) can use these two endpoints.
- `/health` stays public.

`POST /internal/reset` is disabled (404) unless both
`BILLING_SVC_ALLOW_INTERNAL_RESET=true` and `BILLING_SVC_INTERNAL_RESET_TOKEN`
(at least 32 characters) are set, and callers must send the token in
`X-Internal-Reset-Token` (403 otherwise; a bearer token never authorizes a
reset). Published deployments should leave the flag disabled.

`make procs-up NS=<ns>` generates both secrets into the git-ignored
`procs/.secrets/<ns>.env`; `make procs-parity` mints a short-lived admin token
from it, and `make procs-token NS=<ns>` prints one for manual calls.

For the extracted target, a plan change with an already-scheduled later
subscription preserves that later row. The response's `latest_*` fields always
identify the subscription created by the request, rather than relying on row
ordering.

The legacy procedure attempts a second insert for an identical plan change and
therefore relies on the database uniqueness error. The extracted target returns
HTTP 409 with an explicit conflict detail instead of leaking a 500; this is
target-side error handling, not an additional parity rule.

When using the workshop client with the default disposable stack, the Vite
development proxy forwards `/billing-api/*` to the service on port `12109`.
The client sends the signed-in user's platform access token
(`otter_access_token`) with every billing request, so the screens only load for
a caller the service authorizes; for a local run, store a token from
`make procs-token NS=<ns>` under that key. The billing screens are part of this
local parity fixture only. Vite dev
enables their routes by default; a preview requires building with
`VITE_ENABLE_BILLING_FIXTURE=true` and then running `npm run start`. The
`/billing-api` proxy is used by the dev server and by that explicitly flagged
preview. Builds without the flag leave the routes unregistered. No deployed
app or shared-infrastructure deployment is provided for this fixture.
