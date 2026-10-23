# QA audit: analytics-report unit

Scope: `services/analytics-service` (Scala 3 / Akka HTTP, `/api/v1/analytics`) and
`services/report-service` (Java 8 / Spring Boot 2.5, `/api/v1/reports`).

## What was exercised

- **Event ingestion**: `POST /api/v1/analytics/events`: valid events, optional metadata, missing fields, malformed JSON, unknown event types, blank ids, spoofed `userId`.
- **Aggregates and dashboard metrics**: `MetricsAggregator` period windows (`7d/30d/90d/daily/weekly/monthly`), dashboard summary, user activity (20-event cap, ordering), document stats (unique viewers), top content (ranking, limit), active users, storage netting/clamping, CSV/JSON export (escaping, empty export).
- **Report generation and download**: create (202, PENDING, default ~30-day range), async worker (CSV/PDF/Excel routing, max-row truncation, FAILED + errorMessage), list (per user, status filter, completed-only default), get, download lifecycle (409 pending/generating, 404 failed/file-less/missing file, 200 attachment), delete (removes file).
- **Date ranges**: default range, explicit ranges, inverted ranges, `ReportDateUtils` parsing/formatting/inclusive range checks/timezone round-trip.
- **Authn/authz**: gateway JWT enforcement, direct report-service port, cross-user reads of analytics activity and reports.
- **Upstream contract**: `ReportDataFetcher` URLs, query params, Guava cache behaviour, fallback paths.

## Pyramid

| Layer | Location | Tests | Pass | xfail / pending |
|---|---|---|---|---|
| Unit (ScalaTest) | `services/analytics-service/src/test/scala/com/otterworks/analytics/qa/` | 30 | 25 | 5 (`pendingUntilFixed`) |
| Unit (JUnit 4) | `services/report-service/src/test/java/com/otterworks/report/qa/` | 39 | 34 | 5 (`@Ignore`) |
| Functional / API (pytest, gateway) | `tests/api/test_qa_analytics_report.py` | 25 | 16 | 9 (`xfail(strict=True)`) |
| E2E (Playwright) | `frontend/client-app/e2e/qa-analytics-report.spec.ts` | 4 | 3 | 1 (`test.fail`) |
| E2E (computer use) | testing-agent recording, linked from the PR | 1 run | see PR comment | |

Every xfail/pending test is tied to a finding ID below and fails for the stated reason when run with `--runxfail`.
The existing suites still pass: analytics `sbt test` 44 pass / 12 canceled (DB-backed specs, no Postgres on the host), and report `mvn test` 88 run / 0 failures.

Commands:

```bash
cd services/analytics-service && sbt "testOnly com.otterworks.analytics.qa.*"
cd services/report-service && mvn -B test -Dtest='Qa*'
UV_PROJECT_ENVIRONMENT=.venv uv run python -m pytest tests/api/test_qa_analytics_report.py   # stack + analytics/report up
cd frontend/client-app && npx playwright test e2e/qa-analytics-report.spec.ts
```

## Findings

| ID | Severity | Service | Location | Repro | Expected | Actual |
|---|---|---|---|---|---|---|
| RPT-1 | High | report | `ReportDataFetcher.java:77`, `:95`, `:123` | `POST /api/v1/reports {"category":"USAGE_ANALYTICS",...}` and poll | COMPLETED, using real or fallback data | FAILED: `405 Method Not Allowed` because the fetcher calls `GET /api/v1/analytics/events`, which is POST-only. The documented sample-data fallback never runs: Guava throws `UncheckedExecutionException`, but the code catches `ExecutionException`. The same applies to the audit fetch. |
| RPT-3 | High | report | `SecurityConfig.java:36` | `curl localhost:8091/api/v1/reports` with no token | 401 | 200, `permitAll()  // TODO: Add JWT validation`. Only the gateway protects the service. |
| RPT-4 | High | report | `ReportDataFetcher.java:146-148`, `:193-210` | Create a `USER_ACTIVITY` or `STORAGE_SUMMARY` report and download it | Real user data, or a FAILED/partial report | COMPLETED with 25 fabricated users (`user0@otterworks.example.com`…). auth-service returns 403 to report-service, and the fallback rows use `last_login = daysAgo(i % 7)`, which ignores the requested range. |
| RPT-6 | High | report | `ReportController.java:83-110`, `:129`, `:182` | User B runs `GET /api/v1/reports/{A's id}` or `GET /api/v1/reports?userId=A` | 403/404 | 200, with full read/download/delete of other users' reports. `requestedBy` is taken from the request body instead of the JWT. |
| ANL-6 | High | analytics | `EventRoutes.scala:19-30`, `AnalyticsRoutes.scala` (`/users/{id}/activity`) | User B posts an event with `userId=A`, then reads A's activity | 403 | 202/200. There are no ownership checks, and the event `userId` is not bound to the JWT subject. |
| RPT-2 | Medium | report | `ReportRequest.java` / `ReportService.java` (no range check) | `dateFrom=now, dateTo=now-30d` | 400 | 202, and the report is generated over an empty, inverted range |
| ANL-1 | Medium | analytics | `EventRoutes.scala:19-30` | `eventType":"made.up_event"` | 400 (not in `EventType.All`) | 202 accepted and counted in totals |
| ANL-7 | Medium (wiring) | analytics | `EventProcessor.scala:55-68`, `application.conf:25` | Create a document, then read the creator's analytics activity | `documentsCreated >= 1` | 0. The SQS queue `otterworks-analytics-events` is not provisioned in LocalStack, so the processor logs `QueueDoesNotExistException` every 5s. Real uploads and docs never reach analytics locally. |
| ANL-2 | Low | analytics | `EventRoutes.scala:19` | Blank `userId`/`resourceId` | 400 | 202 |
| ANL-3 | Low | analytics | `MetricsAggregator.scala:188` | `GET /dashboard?period=forever` | 400 | 200, computed over 7d but labelled `"period":"forever"` |
| ANL-4 | Low | analytics | `AnalyticsRoutes.scala:66` | `GET /top-content?limit=-5` | 400 | 200 |
| ANL-5 | Low | analytics | `AnalyticsRoutes.scala:104-111` | `GET /export?format=xml` | 400 | 200 JSON |
| RPT-5 | Low | report | `ReportDateUtils.java:29` | `parseIsoDate("2026-01-01T00:00:00Z")` with a non-UTC JVM | Instant at UTC midnight | `'Z'` is a literal, so the value is parsed in the JVM default zone (the shared `SimpleDateFormat` is also not thread-safe) |

## Not tested and why

- **Reports UI**: neither the client app nor the admin dashboard has a reports page. Report generation and download were covered through the signed-in browser session's JWT (Playwright) and the API.
- **Usage-analytics widgets in the UI**: the client dashboard widgets (recent files/docs, activity, storage) come from file-service and document-service, not analytics-service. The admin-dashboard analytics page reads `admin-service /admin/metrics/summary` (another unit; admin-service is not in the core profile). The only analytics-service UI is `/margins`, which is covered.
- **SQS-driven ingestion**: blocked by ANL-7 (queue not provisioned locally). Only direct HTTP ingestion was exercised.
- **DB-backed analytics specs** (`PostgresMetricsRepository`): these are canceled when there is no host Postgres. QA route tests use `InMemoryMetricsRepository`. The running container uses Postgres and was exercised by the API tests.
- **S3 report storage / real AWS**: out of scope (local filesystem output only, and no AWS calls allowed).
