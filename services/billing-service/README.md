# Billing Service

This FastAPI service is the extraction target for the plans module. It owns a
separate `billing_svc` data boundary, keeps the HTTP layer thin, and places
plans behavior in a plain-Python domain layer.

## Development

```bash
uv run --with fastapi --with uvicorn uvicorn app.main:app --reload --port 8097
uv run --with pytest --with httpx pytest
uv run --with ruff ruff check app scripts tests
```

The deterministic target seed is generated from
`services/legacy-billing/db/seed.sql`:

```bash
python scripts/generate_seed.py
```

The generated-seed test prevents the target fixture from drifting from the
legacy before-state. `POST /internal/reset` applies the migration and seed so
the parity harness can isolate every scenario.
