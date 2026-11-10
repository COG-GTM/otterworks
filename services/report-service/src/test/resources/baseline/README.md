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

- **Known pre-existing bug, expected to change (LBG-23):** `GET /api/v1/reports?userId=...`
  and `?status=FAILED` return **500** on PostgreSQL once a FAILED report exists (Hibernate
  "Unable to access lob stream" on the `@Lob errorMessage` column). `behaviour.json` keeps the
  legacy 500 (`listByUser`, `listFailed`). `known-differences.json` marks those keys, so
  `compare` prints them as `KNOWN` and does not fail when they change. Any other difference in
  the same file still fails. Once LBG-23 lands, re-capture `behaviour.json` and remove the entries.
- `DependencyTranscriptEmitterTest` is skipped unless the dependency-remediation harness
  enables it.
- `metrics.json` was captured with a Google Maven Central mirror injected into the builder
  stage only, because Maven Central returned HTTP 429 during `dependency:go-offline`; the
  runtime stage (`eclipse-temurin:8-jre`) is unchanged, so image size and startup are not affected.
