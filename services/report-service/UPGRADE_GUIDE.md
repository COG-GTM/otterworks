# Report Service Dependency Upgrade — Status

The Java 8 / Spring Boot 2.5 → Java 17 / Spring Boot 3.2 migration has been applied
(Jira TTRWRKS-4). This document records what changed, what is left, and how to verify.

## Completed axes

| # | Axis | From | To |
|---|------|------|----|
| 1 | Java version | 1.8 | 17 (`<java.version>`, `maven-compiler-plugin` `<release>`) |
| 2 | Spring Boot | 2.5.14 | 3.2.12 (parent BOM manages compiler/surefire) |
| 3 | Namespace | `javax.*` | `jakarta.*` (persistence, validation, transaction, servlet) |
| 4 | Tests | JUnit 4 | JUnit 5 / Jupiter 5.10 (the `junit-jupiter` exclusion is gone) |
| 5 | API docs | SpringFox 3.0.0 | springdoc-openapi 2.5.0 (`@Bean OpenAPI` in `SwaggerConfig`) |
| 7 | Commons Lang | `commons-lang:2.6` | `org.apache.commons:commons-lang3` (Boot-managed) |
| 8 | Commons IO | 2.6 | 2.15.1 |
| 9 | Guava | 28.0-jre | 33.0.0-jre |
| 10 | Apache POI | 4.1.2 | 5.2.5 |
| 11 | Mockito | 3.12.4 | 5.7.0 (Boot-managed) |
| — | OpenCSV | 4.6 | 5.9 |
| — | HTTP client | HttpComponents 4.5 | HttpClient 5 (Boot-managed; do **not** pin `httpclient5.version` — a pinned 5.4.x against the BOM's httpcore5 5.2.5 fails at runtime with `NoSuchMethodError` on `DefaultHttpRequestWriterFactory`) |

Most of the above was produced by the OpenRewrite recipe
`org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2`.

### Breaking changes fixed by hand

- `SecurityConfig` — Spring Security 6: `XXssConfig.block(boolean)` is gone, replaced with
  `.headerValue(XXssProtectionHeaderWriter.HeaderValue.ENABLED_MODE_BLOCK)`;
  `frameOptions`/`contentTypeOptions` moved out of the deprecated chained form.
  Swagger matchers now cover `/v3/api-docs/**` instead of `/v2/api-docs/**`.
- `AppConfig` — Spring 6: `HttpComponentsClientHttpRequestFactory.setReadTimeout(int)` is gone.
  The read timeout is now a `ConnectionConfig` socket timeout on the pooling connection manager;
  the connect timeout stays on the factory as a `Duration`.
- `SwaggerConfig` — the recipe deleted the SpringFox `Docket` bean but left the `Info` helper
  orphaned; it is re-exposed as an `OpenAPI` bean.
- `application.properties` — dropped the SpringFox `spring.mvc.pathmatch.matching-strategy`
  workaround and the explicit Hibernate dialects (Hibernate 6 auto-detects).

## Behavior notes

- **Trailing slashes no longer match.** Spring Framework 6 disables trailing-slash matching by
  default, so `GET /api/v1/reports/` now 404s where it returned 200 on Boot 2.5. No in-repo
  client relies on it (the frontend never calls this service; the gateway routes without the
  trailing slash). Restore with `WebMvcConfigurer.configurePathMatch(...).setUseTrailingSlashMatch(true)`
  if an external client needs it.
- **`/error` must be permitted.** Spring Security 6 filters the ERROR dispatch, so a
  `SecurityFilterChain` that does not permit `/error` turns *every* error response into a 403 —
  including errors on paths that are themselves permitted. `SecurityConfig` permits it explicitly.

## Remaining tech debt

| Axis | Item | Notes |
|------|------|-------|
| 6 | iText 5.5.13.3 → OpenPDF / iText 7 | Deliberately deferred: iText 7 is a rewrite of the `PdfReportGenerator` API surface and a license decision (AGPL), not a mechanical migration. |
| — | `java.util.Date` → `java.time.*` | Entity, DTOs, and `ReportDateUtils`. |
| — | `RestTemplate` → `RestClient`/`WebClient` | `AppConfig`. |
| — | Trivy exclusion | `services/report-service` is still excluded from dependency scanning (`docs/EVENT_DRIVEN_SECURITY.md`); now that the stack is current, that exclusion should be revisited. |

## Verification

```bash
cd services/report-service
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 mvn -B clean verify
```

Expected: 44 tests across `ReportServiceTest`, `ReportControllerIntegrationTest`,
`CsvReportGeneratorTest`, `PdfReportGeneratorTest`, `ExcelReportGeneratorTest`, all green,
no `spring-boot-properties-migrator` warnings at startup.

CI runs the same build on Temurin 17 (`.github/workflows/ci.yml` job `report-service`, and
`docker-build.yml` job `report-service-tests`).
