# Report Service Upgrade Record

**Status: completed** (epic LBG-16, tickets LBG-17 to LBG-24).

report-service moved from Java 8 / Spring Boot 2.5.15 to **Java 17 / Spring Boot 3.5.16**
without changing its API or report output. This file used to be the step-by-step plan
for the 11 upgrade axes. It now records what was done and which versions are in use.
The per-ticket detail is in the git history and in `src/test/resources/baseline/README.md`.

## Versions

| # | Area | Before | After | Ticket |
|---|------|--------|-------|--------|
| 1 | Java | 1.8 (`eclipse-temurin:8`) | 17 (`maven:3.9-eclipse-temurin-17` builder, `eclipse-temurin:17-jre` runtime, `maven.compiler.release` 17) | LBG-18 |
| 2 | Spring Boot | 2.5.15 | 3.5.16 | LBG-23 |
| 3 | Servlet / persistence / validation | `javax.*` | `jakarta.*` (Hibernate 6, Spring Security 6 `SecurityFilterChain`) | LBG-23 |
| 4 | Tests | JUnit 4 | JUnit 5 (Jupiter, via `spring-boot-starter-test`) | LBG-19 |
| 5 | API docs | SpringFox 3.0.0 (`/v2/api-docs`) | springdoc-openapi 2.8.17 (`/v3/api-docs`) | LBG-20, LBG-23 |
| 6 | PDF | iText 5.5.13.3 | OpenPDF 2.0.5 (last Java 17 line, still `com.lowagie` packages) | LBG-22, LBG-23 |
| 7 | Commons Lang | `commons-lang` 2.6 | `commons-lang3` 3.14.0 | LBG-21 |
| 8 | Commons IO | 2.6 | 2.15.1 | LBG-21 |
| 9 | Guava | 28.0-jre | 33.7.2-jre | LBG-21, LBG-24 |
| 10 | Apache POI | 4.1.2 | 5.2.5 | LBG-21 |
| 11 | Mockito | 3.x | 5.24.0 | LBG-19, LBG-23 |
| 12 | HTTP client behind `RestTemplate` | Apache HttpClient 4 | HttpClient 5.6.5 / HttpCore 5.4.4 | LBG-23, LBG-24 |
| 13 | OpenCSV | 4.x | 5.12.0 | LBG-21 |

`pom.xml` also overrides a few versions managed by the Boot 3.5.16 BOM (Jackson 2.21.8,
Tomcat 10.1.59, PostgreSQL JDBC 42.7.14, HttpClient/HttpCore above) to close Trivy
CRITICAL/HIGH findings. Drop each override once the parent manages that version or newer.

## Deliberately unchanged

- **commons-text 1.9.** It is the CVE under test (CVE-2022-42889) for the
  dependency-remediation exercise in `security/deps`. Trivy reports it, and it is
  suppressed for `services/report-service/pom.xml` only, in
  `security/scanning/trivy-scoped-ignores.json`. The deps harness builds this module on
  JDK 17 and gets Nashorn for the recorded `${script:javascript:...}` case from the
  test-scoped `org.openjdk.nashorn:nashorn-core` dependency.
- `RestTemplate` (no WebClient/RestClient rewrite), `java.util.Date` in the model, and the
  other patterns marked `LEGACY` in the source. They still apply and are follow-up work.

## Behaviour changes

All are recorded in the baseline (`src/test/resources/baseline/`):

- `GET /api/v1/reports?userId=` and `?status=FAILED` no longer return 500 on PostgreSQL.
  `errorMessage` is plain `text`; `LegacyErrorMessageMigration` inlines rows written by the
  Boot 2 build.
- Spring Security 6 denies unmatched paths: **403** instead of 404.
- API docs are OpenAPI 3 at `/v3/api-docs`. The paths, operations and schemas match the
  old `/v2/api-docs`.
- OpenPDF wraps one timestamp cell at a different point; the extracted text is the same.
- `/actuator/info` needs `management.info.env.enabled=true` (set) and trailing-slash
  paths are handled by `WebConfig` because Spring MVC 6 no longer matches them.

## Known residual findings

Trivy without `--offline-scan` (the mode `sast-auto-remediate.yml` uses) still reports
`org.springframework:spring-webmvc` 6.2.19 for CVE-2026-47884 (XsltView) and
CVE-2026-47890 (SSE with view fragments). The only fixed release is Spring Framework
7.0.9 (Spring Boot 4); 6.2.19 is the newest open-source 6.2.x and the BOM's version.
report-service uses neither `XsltView` nor SSE. These findings are not suppressed.

## Verify

```bash
cd services/report-service
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 mvn -B verify
cd ../.. && make deps-transcript-baseline MODULE=report-service
```

Behaviour against a running service: `uv run scripts/baseline.py compare` (see
`src/test/resources/baseline/README.md`).
