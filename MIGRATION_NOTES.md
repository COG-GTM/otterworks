# Java 8/11 → Java 17, Spring Boot 2.x → 3.2 migration

Scope: the two Maven services still on a pre-3.x Spring Boot line.
`auth-service` (Boot 3.2.4 / Java 17, Gradle) and `notification-service` (Kotlin/Ktor,
`jvmToolchain(17)`) were already current and are untouched.

| Service | Before | After |
|---|---|---|
| `services/report-service` | Boot 2.5.14, Java 8 | Boot 3.2.5, Java 17 |
| `services/legacy-portal` | Boot 2.7.18, Java 11 | Boot 3.2.5, Java 17 |

## How

- OpenRewrite `org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2` did the bulk
  (Boot property/API migrations, `javax.*` → `jakarta.*`, Java 17 build target,
  JUnit 4 → 5, Spring Security 5 → 6), followed by a manual sweep per service.
- One migration subsession per service, each scoped to its own directory; shared/root
  files (CI, docs, these notes) were handled in the parent session.

## report-service (44 tests green on JDK 17)

- Parent `spring-boot-starter-parent` 3.2.5, `java.version` 17; the hand-pinned
  `maven-compiler-plugin` / `maven-surefire-plugin` blocks are gone (the Boot parent manages them).
- `javax.persistence|validation|transaction` → `jakarta.*`; the explicit `javax.servlet-api`
  dependency is dropped (the web starter brings `jakarta.servlet-api`).
- `SecurityConfig` is a `@Bean SecurityFilterChain` (`authorizeHttpRequests()` / `requestMatchers()`)
  with the same rules as the old `WebSecurityConfigurerAdapter`.
- **SpringFox 3.0.0 → springdoc-openapi 2.3.0.** SpringFox does not run on Boot 3 at all, so
  `SwaggerConfig` is now an `OpenAPI` bean. **API docs move from `/v2/api-docs` to `/v3/api-docs`**
  (security permitAll updated); the `spring.mvc.pathmatch.matching-strategy=ant-path-matcher`
  SpringFox workaround is removed from both property files.
- **iText 5.5.13.3 → OpenPDF 1.3.35** (drop-in fork, also sheds the AGPL question). OpenPDF has no
  `BaseColor`, so `PdfReportGenerator` uses `java.awt.Color` with identical RGB values; the PDF
  tests pass unmodified.
- **Apache HttpClient 4 → 5** in `AppConfig` — Spring Framework 6 dropped the HC4 request factory.
  Same connect/read timeouts, now set on the pooling connection manager (HC5 moved them off
  `RequestConfig`).
- Dependency floor for Java 17: POI 5.2.5, commons-io 2.15.1, Guava 33.1.0-jre, OpenCSV 5.9,
  `commons-lang:2.6` → `commons-lang3:3.14.0`.
- Tests: JUnit 4 → 5. The `junit-jupiter` exclusion, `junit:junit` and the pinned `mockito-core`
  are removed; the Boot BOM supplies JUnit 5.10.2 / Mockito 5.7.0.
- Dockerfile: `maven:3.9-eclipse-temurin-17` builder, `eclipse-temurin:17-jre` runtime.
- Added a `.gitignore` for the service (`target/` was previously not ignored here).
- Runtime-testing fallout, fixed here: Hibernate 6 maps `@Lob String` to a Postgres large object
  (`oid`), so `Report.errorMessage` is pinned back to a text column with
  `@JdbcTypeCode(SqlTypes.LONGVARCHAR)`; Security 6 denies unmatched requests, so `SecurityConfig`
  now permits `/error` plus a terminal `anyRequest().permitAll()` (otherwise every 404/500 came back
  as an empty 403) and `/swagger-ui.html` (the configured UI path, previously only `/swagger-ui/**`).
  The explicit `hibernate.dialect` properties are dropped here too (`HHH90000025`).

## legacy-portal (13 tests green on JDK 17)

- Parent 3.2.5, `java.version`/compiler 17; `javax.persistence|validation` → `jakarta.*`.
- Hibernate 5.6 → 6.4: the explicit `hibernate.dialect` is removed for both the H2 default and the
  `postgres` profile (auto-detected now). `ddl-auto: update` may generate slightly different DDL
  against a pre-existing database.
- No property renames were needed — `spring-boot-properties-migrator` was run temporarily and
  reported nothing, then removed.
- Dockerfile: `maven:3.9-eclipse-temurin-17` builder, `eclipse-temurin:17-jre-jammy` runtime.
  The Maven wrapper was already 3.9.9. No Java 11 references existed in `scripts/`, `deploy/`, or
  `docker-compose.onprem.yml`.

Neither service needed an `--add-opens` argLine, and no MockMvc trailing-slash fixes were required
(no mapping or test used a trailing slash). No tests were weakened, skipped, or deleted.

## CI

- `report-service` job: Temurin 8 → Temurin 17, `mvn compile`/`test`/`package` collapsed
  into `mvn -B verify`, with `cache: maven` dependency caching.
- `legacy-portal` job (added on `main` while this branch was in flight): Temurin 11 → 17,
  `./mvnw test` → `./mvnw -B verify`, with `cache: maven`.

## Follow-ups (not in this PR)

- `services/report-service` is still excluded from the Trivy scan
  (`--skip-dirs` in `.github/workflows/security-scan.yml`) as an intentionally-legacy
  service. Its dependencies are now current, so the exclusion can be dropped once someone
  is ready to triage whatever the first full scan reports.
- Both services were booted on JDK 17 and exercised end-to-end against a `main` baseline
  (see the verification comment on the PR). Not covered there: `USAGE_ANALYTICS` reports
  (downstream `analytics-service` unavailable; its fallback gap pre-exists on `main`) and
  the legacy-portal on-prem profile.
