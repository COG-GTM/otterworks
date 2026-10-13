# Testing overview

| Layer | Where | How it runs in CI |
| --- | --- | --- |
| Unit / component tests | `services/*/` | Per-service jobs in `.github/workflows/ci.yml`, with coverage gates ([coverage-thresholds.md](coverage-thresholds.md)) |
| Contract lint | `shared/proto/` (buf), `shared/openapi/` (Redocly, `redocly.yaml`) | `.github/workflows/contracts.yml` |
| Black-box API flows | `tests/api/` | `.github/workflows/api-flows-live.yml` runs `make test-api-flows` against a live docker-compose core stack; `ci.yml` keeps a fast `--collect-only` check for all flows |
| Load / performance | `tests/perf/` (k6) | `.github/workflows/perf.yml` (manual + weekly) |

## API flows against a live stack

```bash
/home/ubuntu/otterworks-up.sh            # or: docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d <core services>
uv venv .venv && VIRTUAL_ENV=.venv uv pip install -r tests/api/requirements.txt
make test-api-flows                      # all flows
PYTEST_ADDOPTS='-k "test_auth_flow or test_file_flow or test_document_flow"' make test-api-flows   # core-profile flows only (what CI runs)
```

The core profile (api-gateway, auth, file, document, web-app + postgres/redis/localstack/meilisearch)
only serves the auth, file and document flows. Search, notification, admin, audit, analytics, report,
collab and the cross-service side-effect flows need the full 13-service stack and fail with 502 from
the gateway without it; running them in CI is a follow-up (bigger runner or a scheduled full-stack job).
