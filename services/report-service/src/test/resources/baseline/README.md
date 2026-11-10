# report-service behaviour baseline (LBG-17)

Captured from the **legacy stack** (Java 8 / Spring Boot 2.5.15, SpringFox, POI 4, iText 5)
before the Java 17 / Spring Boot 3 upgrade (epic LBG-16). Upgrade tickets compare their
build against this directory with `scripts/baseline.py`.

| Path | What it is | Compared |
|------|------------|----------|
| `tests/surefire-summary.txt` | `mvn -B test` on JDK 8: passed/failed/skipped per class | `tests` |
| `contract/api-docs.json` | Raw `/v2/api-docs` (Swagger 2, SpringFox) | informational |
| `contract/api-summary.txt` | Operations, params, request/response models, normalised so Swagger 2 and OpenAPI 3 (springdoc) compare equal | strict |
| `contract/api-responses.txt` | Documented response codes per operation (generator-specific) | informational |
| `contract/health.json`, `actuator-health.json`, `actuator-info.json` | `/health`, `/actuator/health`, `/actuator/info` | strict |
| `contract/actuator-prometheus-families.txt` | Metric family names and types from `/actuator/prometheus` | informational |
| `contract/behaviour.json` | Status codes for validation errors, unknown ids, listing, and a report whose upstream is unreachable | strict |
| `raw/report.{pdf,csv,xlsx}` | One downloaded report per format | not diffed |
| `reports/pdf.txt` | Text extracted from the PDF (pypdf), timestamps masked | strict |
| `reports/csv.csv` | CSV with timestamps masked | strict |
| `reports/xlsx.txt` | Every non-empty cell: coordinate, type, value | strict |
| `reports/metadata.json` | `ReportResponse` + download headers per format, ids/timestamps removed | strict |
| `reports/info.json` | File sizes, upstream error message | informational |
| `known-differences.json` | Strict JSON keys expected to change, with the owning ticket; `compare` reports them as `KNOWN` | — |
| `metrics.json` | Docker image size and time from container start to `/health` | `metrics` (prints deltas) |

`compare` exits non-zero only on **strict** differences; informational files are diffed
but expected to move with the framework (e.g. SpringFox → springdoc, Micrometer metric names).
A deliberate change to a strict file must be re-captured and explained in the PR.

## Comparing an upgraded build

Needs Docker, [uv](https://docs.astral.sh/uv/), and the service running against PostgreSQL
with the other services **not** running (USAGE_ANALYTICS is captured as failing because
analytics-service is unreachable; USER_ACTIVITY falls back to synthetic users).

```bash
cd services/report-service
mvn -B test && uv run scripts/baseline.py tests          # per-class test counts vs baseline

cd ../..
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d postgres
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d --build --no-deps report-service
cd services/report-service
uv run scripts/baseline.py compare                       # API contract + report output
uv run scripts/baseline.py metrics --no-build            # image size / startup vs baseline
```

`compare --url http://host:port` targets a service started any other way (e.g. `java -jar`
with `DB_*` env vars). `compare --out DIR` keeps the current capture for inspection.

## Regenerating

Only regenerate from the legacy stack, or deliberately when an approved behaviour change lands:

```bash
JAVA_HOME=/path/to/jdk8 mvn -B test && uv run scripts/baseline.py tests --update
uv run scripts/baseline.py capture                        # service on :8091
uv run scripts/baseline.py metrics --update               # rebuilds the image via docker compose
```

## Known legacy behaviour recorded here

- **Fixed in LBG-23:** the legacy build returned **500** for `GET /api/v1/reports?userId=...`
  and `?status=FAILED` on PostgreSQL once a FAILED report existed (Hibernate 5 "Unable to access
  lob stream" on the `@Lob errorMessage` column). `errorMessage` is now mapped as plain `text`,
  `behaviour.json` was re-captured with 200 for `listByUser` and `listFailed`, and
  `known-differences.json` is empty.
- **Legacy rows (LBG-23):** the Boot 2 build stored `error_message` as a large-object OID.
  On startup `LegacyErrorMessageMigration` copies each message back into the column, one row at
  a time (a row whose large object is not valid UTF-8 is skipped with a WARN and keeps its OID).
  It never unlinks large objects; remove the orphans with `vacuumlo -v <database>` once every
  instance runs the Boot 3 build.
- **Deny by default (LBG-23):** Spring Security 6 denies requests that match no rule, so a path
  no controller serves returns **403** instead of the legacy 404. `behaviour.json` records it as
  `unknownPath: 403` (re-captured from the Boot 3 build).
- **PDF wrapping (LBG-22):** `reports/pdf.txt` was re-captured in LBG-23 from the OpenPDF build.
  The extracted text is identical, but OpenPDF wraps the `last_login` cell at the hyphen
  (`2026-11-` / `10T…Z`) where iText 5 wrapped before the `Z`. The change came with the
  iText 5 → OpenPDF swap in LBG-22 (the base-branch OpenPDF 1.3.43 jar shows it too), not
  with Boot 3 or OpenPDF 2. `baseline.py` now masks a timestamp that wraps across lines as
  `<TIMESTAMP>` too, so the wrapped `Z` is part of the mask.
- `DependencyTranscriptEmitterTest` is skipped unless the dependency-remediation harness
  enables it.
- `metrics.json` was captured with a Google Maven Central mirror injected into the builder
  stage only, because Maven Central returned HTTP 429 during `dependency:go-offline`; the
  runtime stage (`eclipse-temurin:8-jre`) is unchanged, so image size and startup are not affected.
