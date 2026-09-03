# Java 17 / Spring Boot 3.2 migration notes

Inventory: `docs/java17-migration-intake.yaml`. Every JVM service in the repo is now on
Java 17 in all three places that count — build file, Dockerfile base images, CI `java-version`.

| Service | Build | Before | After | Class |
|---|---|---|---|---|
| `services/report-service` | Maven | Java 8 / Spring Boot 2.5.15 / `maven:3.8.7-eclipse-temurin-8` + `eclipse-temurin:8-jre` / CI `'8'` | Java 17 / Spring Boot 3.2.5 / `maven:3.9-eclipse-temurin-17` + `eclipse-temurin:17-jre-jammy` / CI `'17'` | migrate |
| `services/legacy-portal` | Maven (`./mvnw`) | Java 11 / Spring Boot 2.7.18 / `maven:3.9-eclipse-temurin-11` + `eclipse-temurin:11-jre-jammy` / CI `'11'` | Java 17 / Spring Boot 3.2.5 / `maven:3.9-eclipse-temurin-17` + `eclipse-temurin:17-jre-jammy` / CI `'17'` | migrate |
| `services/auth-service` | Gradle | Java 17 / Spring Boot 3.2.4 / `gradle:8.6-jdk17` + `eclipse-temurin:17-jre-jammy` / CI `'17'` | unchanged (verified) | verify |
| `services/notification-service` | Gradle KTS (Kotlin 1.9.23, Ktor 2.3.9) | `jvmToolchain(17)` / `gradle:8.6-jdk17` + `eclipse-temurin:17-jre-jammy` / CI `'17'` | unchanged (verified) | jdk-only |
| `services/analytics-service` | sbt (Scala 3.4.0, Akka HTTP 10.5.3) | `sbtscala/scala-sbt:eclipse-temurin-jammy-17.0.10…` + `eclipse-temurin:17-jre-jammy` / CI `'17'` | unchanged (verified) | jdk-only |

Excluded: `frontend/client-app/mobile/android` (Android Gradle project, not a server-side JVM service; already on JDK 17).

## report-service (Java 8 / Boot 2.5.15 → Java 17 / Boot 3.2.5)

OpenRewrite `org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2` did:
- Boot parent → 3.2.x, `<java.version>17</java.version>`; dropped the explicit `maven.compiler.*`,
  compiler/surefire plugin versions, `mockito-core` version and the `javax.servlet-api` dependency
  (all managed by the Boot parent or provided by Tomcat 10).
- `javax.persistence` / `javax.validation` / `javax.annotation` → `jakarta.*` across entities,
  controllers and config.
- JUnit 4 → JUnit 5 (`@Test`, `@BeforeEach`, `Assertions`, `Assumptions`) in all 7 test classes and
  removed the `junit:junit` dependency and the Jupiter exclusion on `spring-boot-starter-test`.
- `commons-lang` 2.6 → `commons-lang3` (managed) and `StringUtils` import updates.
- Removed `spring.mvc.pathmatch.matching-strategy=ant-path-matcher` (SpringFox workaround).

Hand-fixed after the recipe:
- Pinned the parent to exactly 3.2.5 (recipe picked the latest 3.2.x).
- Spring Security 6: `WebSecurityConfigurerAdapter` → `SecurityFilterChain` bean with the lambda
  DSL (`authorizeHttpRequests` / `requestMatchers` / `headers(...)`), plus
  `dispatcherTypeMatchers(DispatcherType.ERROR).permitAll()` so 400/404 responses reach the
  client as JSON errors instead of empty 403s (Security 6 authorizes the ERROR dispatch too).
- SpringFox 3 (dead, incompatible with Spring 6) → `springdoc-openapi-starter-webmvc-ui` 2.5.0:
  `@Api*` → `@Schema` / `@Operation`, `Docket` → `OpenAPI` bean, docs now at `/v3/api-docs` and
  `/swagger-ui.html` (were `/v2/api-docs`, `/swagger-ui/`); security matchers updated accordingly.
- Hibernate 6: `Report.errorMessage` (`@Lob String`) annotated `@JdbcTypeCode(SqlTypes.LONGVARCHAR)`
  so the column stays `varchar` instead of becoming a Postgres `oid`. Verified: `reports.error_message`
  is `character varying(32600)` against Postgres 15.
- Apache HttpClient 4 → HttpClient 5 (Spring 6 dropped the 4.x request factory); read timeout moved to
  `SocketConfig` on the pooling connection manager.
- Removed the explicit `hibernate.dialect` properties (Hibernate 6 auto-detects and warns otherwise).
- Dockerfile builder/runtime → `maven:3.9-eclipse-temurin-17` / `eclipse-temurin:17-jre-jammy`.
- Kept deliberately: `commons-text` 1.9 (CVE-2022-42889 fixture for the dependency-remediation lab),
  POI 4.1.2, iText 5.5.13.3, Guava 28, Commons IO 2.6 — out of scope for this migration.

`--add-opens`: none. Tests: 50 run / 0 failed / 1 skipped before (JUnit 4, JDK 8) and after (JUnit 5,
JDK 17); the skipped test is the opt-in dependency-transcript emitter.

## legacy-portal (Java 11 / Boot 2.7.18 → Java 17 / Boot 3.2.5)

OpenRewrite did:
- Boot parent → 3.2.x, `<java.version>17</java.version>`, dropped redundant `maven.compiler.*`.
- `javax.persistence` / `javax.validation` / `javax.annotation` → `jakarta.*` in 7 source files
  (`Announcement`, `Feedback`, `UserPreference` entities and their controllers, `PortalBrandingSettings`).
- Split the `postgres` profile out of `application.yml` into `application-postgres.yml` (Boot 3 no
  longer accepts multi-document profile activation the old way).

Hand-fixed after the recipe: exact 3.2.5 parent; removed explicit Hibernate dialect settings;
Dockerfile builder/runtime → `maven:3.9-eclipse-temurin-17` / `eclipse-temurin:17-jre-jammy`;
removed stale "Java 11" comments in `README.md`/`Dockerfile`. No Spring Security, no `@Lob`, no
`spring.factories`, no JAXB/Nashorn — as expected coming from 11, there was little beyond the
namespace change. `commons-configuration2` 2.8.0 kept (transitive `commons-text` 1.9 fixture).

`--add-opens`: none. Tests: 16 run / 0 failed / 1 skipped before and after.

## Shared files (lead)

- `.github/workflows/ci.yml`, `.github/workflows/docker-build.yml`: report-service and legacy-portal
  jobs now `setup-java` Temurin `'17'` with `cache: maven`.
- `.github/workflows/deps-remediation.yml`, `security/deps/modules.yaml`,
  `.agents/skills/dependency-cve-remediation/SKILL.md`: the dependency-remediation harness measures
  the two Maven modules on JDK 17 instead of JDK 11.
- `README.md`: service table no longer describes report-service as Java 8 / Boot 2.5.

## Runtime verification (JDK 17, against Postgres 15 via `docker-compose.infra.yml`)

Both migrated apps start on Boot 3.2.5 with no `spring-boot-properties-migrator` findings
(only the default `spring.jpa.open-in-view` notice that Boot 2.x also logged).

report-service (`:8091`): `/health`, `/actuator/health`, `/v3/api-docs`, `/swagger-ui/index.html` → 200;
`POST /api/v1/reports` → 202, report reaches `COMPLETED` (CSV, 25 rows), `GET /api/v1/reports/{id}` → 200,
list → 200, `DELETE` → 204, unknown id → 404, bad id → 400 JSON.

legacy-portal (`:8095`, `postgres` profile): `/health`, `/actuator/health` → 200; announcements
create 201 / publish 200 / list 200; preferences put+get 200; feedback submit 201 (validation errors
still 400) / list 200 / average-rating 200; unknown announcement → 404.

Behaviour differences vs `main` worth knowing:
- Trailing-slash URLs (`/api/v1/reports/`, `/api/announcements/`) now 404 (Boot 3 / Spring 6 default).
  No caller uses them — the API gateway routes `/api/v1/reports` and the frontend never calls either
  service directly.
- report-service paths not covered by a security matcher (e.g. `/nope`) now return 403 instead of 404
  (Security 6 denies unmatched requests). Not reachable through the gateway.
- Swagger moved from `/v2/api-docs` + `/swagger-ui/` to `/v3/api-docs` + `/swagger-ui.html`.

## Dependency-remediation harness

`security/deps/expected/{report-service,legacy-portal}.json` were re-recorded on JDK 17
(`make deps-record MODULE=<id> ALLOW_RERECORD=1 REASON=...`). The previous recordings came from
JDK 11, where `${script:javascript:3+4}` resolved to `7` via Nashorn; on 17 there is no script
engine, so the vulnerable-baseline outcome for `attack-script-lookup` is now an
`IllegalArgumentException`. The remediated contract is unaffected: with a fixed commons-text the
case must read back `ok` with the literal template, which is still a different outcome from the
baseline, so the `attack` policy grades exactly as before. Legacy-portal's cases contain no
script lookup; only its recording metadata changed. `make deps-transcript-baseline` passes on 17.

## Follow-ups

- `services/report-service/UPGRADE_GUIDE.md` and `docs/{CI_STRATEGY,EVENT_DRIVEN_SECURITY,SDLC-COVERAGE}.md`,
  `docs/labs/security-sprint-guide.md`, `.devin/wiki.json` still describe report-service as Java 8;
  the Trivy exclusion for report-service in `security-scan.yml` can be reconsidered now that it is on 17.
- `infrastructure/helm/report-service/Chart.yaml` description says "Java 8/Spring Boot 2.5" — charts
  ship from upstream `main`, so this needs an upstream PR rather than a change here.
- Library modernisation deliberately left out: POI 4 → 5, iText 5 → OpenPDF, Guava 28 → 33,
  Commons IO 2.6 → 2.15, `java.util.Date` → `java.time`, RestTemplate → RestClient.
- Add JWT validation on `/api/v1/reports/**` (pre-existing TODO, unchanged).
