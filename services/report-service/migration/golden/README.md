# report-service golden fixtures (Java 8 baseline)

Behaviour contract for the Java 8 → 21 migration. Recorded from the Java 8 /
Spring Boot 2.5.15 build of `services/report-service`. Phase 5 replays the same
requests against the Java 21 build and must match.

| Path | What |
|------|------|
| `replay.py` | Records (`--record`) or replays the requests and diffs normalized results |
| `fixtures/*.json` | One normalized response per case (the contract that is compared) |
| `files/` | Raw downloaded PDF / CSV / XLSX and the raw Swagger doc, for reference only (never compared byte-for-byte) |

## Run it

```bash
# from the repo root: Java 8 service + Postgres only (analytics/audit/auth must NOT run)
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d --build postgres report-service
until curl -sf localhost:8091/health; do sleep 2; done

uv run services/report-service/migration/golden/replay.py            # compare, exit 1 on any diff
uv run services/report-service/migration/golden/replay.py --record   # re-record (baseline only)
```

Options: `--base-url`, `--api-docs-path` (default `/v2/api-docs`; springdoc serves
`/v3/api-docs`, compared by the same operation list), `--swagger-ui-path`,
`--actual-dir DIR` (write this run's normalized results for inspection).

Run it with analytics-, audit- and auth-service down. Replaying with those services up
changes the data and fails the diff by design.

## Recorded Java 8 behaviour worth knowing

The fixtures record what the Java 8 build does today, defects included, so the Java 21 build
can be checked against it. A deliberate fix in a later phase means re-recording the affected
fixtures in that PR.

- Analytics- and audit-backed categories (`USAGE_ANALYTICS`, `COLLABORATION_METRICS`,
  `SYSTEM_HEALTH`, `AUDIT_LOG`, `COMPLIANCE`) end `FAILED` when those services are
  unreachable: Guava's `LoadingCache.get(key, Callable)` wraps the `RestClientException` in
  `UncheckedExecutionException`, so the `catch (ExecutionException)` sample-data fallback in
  `ReportDataFetcher` never runs. Their downloads return `404` (no file).
- `USER_ACTIVITY` and `STORAGE_SUMMARY` use the auth-service fallback and complete with 25
  sample rows (`last_login` is relative to now).
- `GET /api/v1/reports?userId=…` and `?status=FAILED` return `500`
  (`Large Objects may not be used in auto-commit mode` on the `fileData` LOB);
  `?status=COMPLETED` and the default list return `200`.

## What is covered

- `GET /health`, `/actuator`, `/actuator/health`, `/actuator/info`, `/actuator/prometheus`
  (status, content type, presence of key metric families), `/actuator/env` (not exposed)
- Swagger: API docs operation list + title/version, Swagger UI status
- `POST /api/v1/reports` for all 7 categories × 3 formats (PDF, CSV, EXCEL), plus 400 cases
  (missing fields, bad enum, malformed JSON)
- `GET /api/v1/reports/{id}` after generation, `GET /api/v1/reports/{id}/download` with
  extracted content, `GET /api/v1/reports` by user / by status / default, `?status=BOGUS`
- `DELETE /api/v1/reports/{id}` for every report, then 404s for get / download / delete
  of missing ids

Not covered: the `409` download response while a report is still `PENDING`/`GENERATING`
(generation finishes in milliseconds, so it cannot be hit deterministically).

## Normalization

- Report `id` → case key (e.g. `audit_log_pdf`); `downloadUrl` uses the key
- `createdAt`, `completedAt`, error-body `timestamp` → `<timestamp>` (null stays null)
- `errorMessage`: the `: Temporary failure in name resolution` suffix (present only on the
  JVM's first lookup of a missing host) is dropped
- `fileSizeBytes` exact for CSV, `<positive>` for PDF / XLSX
- `Content-Disposition` filename timestamp → `_<timestamp>.`
- List responses are filtered to `requestedBy = golden-fixture-user` (the replay deletes
  leftovers of that user before it starts: those it can list, plus the IDs an interrupted run
  left in the git-ignored `.replay-inflight.json`), so other data in the database is ignored
- CSV: parsed rows; `# Generated:` banner time masked
- XLSX: sheet order, cell values per row, merged ranges and auto-filter; `Generated:` masked
- PDF: whitespace-separated text tokens (pypdf); `Generated:` time masked
- `last_login` (user-activity fallback data is relative to now) masked in CSV / XLSX;
  ISO timestamps (with or without the split-off `Z`) masked in USER_ACTIVITY / STORAGE_SUMMARY PDFs
- Prometheus: only whether `http_server_requests_seconds_count`, `jvm_memory_used_bytes`,
  `jvm_threads_live_threads`, `process_uptime_seconds`, `hikaricp_connections_active`,
  `system_cpu_count` are present
