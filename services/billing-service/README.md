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

The reset endpoint is disabled by default. Disposable local/CI Compose stacks
enable it with `BILLING_SVC_ALLOW_INTERNAL_RESET=true`; published deployments
should leave the setting disabled.

For the extracted target, a plan change with an already-scheduled later
subscription preserves that later row. The response's `latest_*` fields always
identify the subscription created by the request, rather than relying on row
ordering.

When using the workshop client with the default disposable stack, the Vite
development proxy forwards `/billing-api/*` to the service on port `12109`.
