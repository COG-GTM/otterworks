# Java 17 / Spring Boot 3.2 migration (TTRWRKS-10)

Every JVM service in the repo is now on Java 17: build file, Dockerfile base images and CI
job pin all agree. The two pre-17 services were migrated; the other three were already
compliant and are recorded here so the inventory is complete.

| service | build | java | framework | class | outcome |
|---|---|---|---|---|---|
| report-service | maven | 8 → **17** | Boot 2.5.14 → **3.2.12** | migrate | 44/44 tests green |
| legacy-portal | maven | 11 → **17** | Boot 2.7.18 → **3.2.12** | migrate | 13/13 tests green |
| auth-service | gradle | 17 | Boot 3.2.4 | verify | no change needed |
| notification-service | gradle-kts | 17 (`jvmToolchain(17)`) | Ktor 2.3.9 / Kotlin 1.9.23 | jdk-only | no change needed |
| analytics-service | sbt | 17 | akka-http / Scala 3.4.0 | jdk-only | no change needed |

The full inventory, including the non-JVM services that are out of scope, is in
[`docs/java17-migration-intake.yaml`](docs/java17-migration-intake.yaml).

Boot patch level is **3.2.12** (the latest 3.2.x) rather than the 3.2.5 default in the
playbook — same minor line, with the intervening CVE fixes.

## report-service (Java 8 / Boot 2.5.14 → Java 17 / Boot 3.2.12)

Automated by OpenRewrite (`rewrite-spring:org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2`):

- `javax.*` → `jakarta.*` (persistence, validation, transaction, servlet)
- JUnit 4 → JUnit 5 (`@RunWith(SpringRunner.class)` dropped, `org.junit.Test` → Jupiter)
- Spring Security 5 → 6: `WebSecurityConfigurerAdapter` → a `SecurityFilterChain` bean,
  `authorizeRequests`/`antMatchers` → `authorizeHttpRequests`/`requestMatchers`
- SpringFox 3 → springdoc-openapi 2: `@Api`/`@ApiOperation`/`@ApiModelProperty` →
  `@Tag`/`@Operation`/`@Schema`
- commons-lang 2 → commons-lang3, Apache HttpClient 4 → HttpClient 5
- Java 17 build target, `eclipse-temurin:8-jre` → `17-jre`, Mockito/surefire versions
  handed back to the Boot parent

Hand-fixed afterwards:

- **springdoc bean**: the recipe left `apiInfo()` orphaned after deleting the SpringFox
  `Docket`; added an `OpenAPI` bean and repointed the permitted doc paths at `/v3/api-docs`
  and `/swagger-ui.html`. Dropped the SpringFox-only
  `spring.mvc.pathmatch.matching-strategy=ant-path-matcher` workaround and unquoted the
  generated `springdoc.packages-to-scan` value.
- **Security 6 headers**: the generated `frameOptions(o -> o.deny().contentTypeOptions())`
  did not compile as intended and `xssProtection().block(true)` no longer exists —
  rewritten to separate `frameOptions` / `contentTypeOptions` / `xssProtection(headerValue=
  ENABLED_MODE_BLOCK)` calls.
- **HttpClient 5 read timeout**: `HttpComponentsClientHttpRequestFactory.setReadTimeout` is
  gone; the socket timeout now lives on the pooling connection manager's
  `ConnectionConfig`.
- **Hibernate 6 `@Lob String`**: `Report.errorMessage` would have been remapped to a
  PostgreSQL `oid` column and broken at runtime — annotated
  `@JdbcTypeCode(SqlTypes.LONGVARCHAR)`.
- Dockerfile builder `maven:3.8.7-eclipse-temurin-8` → `maven:3.9-eclipse-temurin-17`,
  runtime pinned to `eclipse-temurin:17-jre-jammy`.
- Dependency bumps the recipe left alone: POI 4.1.2 → 5.2.5, commons-io 2.6 → 2.15.1,
  Guava 28.0 → 33.0.0-jre, OpenCSV 4.6 → 5.9.

Tests: 44 before (JUnit 4, JDK 8) → 44 after (JUnit 5, JDK 17), all passing. No
`--add-opens` was needed. No property-migrator warnings after the pathmatch property was
removed.

## legacy-portal (Java 11 / Boot 2.7.18 → Java 17 / Boot 3.2.12)

As expected coming from 11 rather than 8, this was much smaller. OpenRewrite did all the
code changes — `javax.persistence`/`javax.validation` → `jakarta.*` across the three
bounded contexts, the Boot parent and Java 17 build target, and the runtime base image.

Hand-fixed afterwards:

- The recipe **deleted the second YAML document** in `application.yml` (the `postgres`
  on-prem profile used by `docker-compose.onprem.yml` / `scripts/run-onprem.sh`) while
  rewriting the file; restored verbatim.
- Removed the redundant `maven.compiler.source`/`target` overrides (`java.version` is
  enough) and bumped the Dockerfile builder to `maven:3.9-eclipse-temurin-17`.

Tests: 13 before → 13 after, all passing. No `--add-opens`, no property renames.

## Already on 17 (verified, not changed)

- **auth-service** — `sourceCompatibility = JavaVersion.VERSION_17`, Boot 3.2.4,
  `gradle:8.6-jdk17` / `eclipse-temurin:17-jre-jammy`, CI pinned to 17.
- **notification-service** — Kotlin/Ktor, `jvmToolchain(17)`, same images, CI pinned to 17.
  No `jakarta` work applies (no Spring).
- **analytics-service** — Scala 3 / akka-http on the `sbtscala/scala-sbt:...temurin...17`
  image, CI pinned to 17.

## CI

`report-service` and `legacy-portal` jobs in `.github/workflows/ci.yml` and their
image-gating test jobs in `.github/workflows/docker-build.yml` moved from
`java-version: '8'` / `'11'` to `'17'`, with `cache: maven` added.

## Follow-ups

- report-service still uses iText 5.5.13.3 (AGPL) — axis 6 of
  `services/report-service/UPGRADE_GUIDE.md`, unchanged here.
- report-service still uses `RestTemplate` and `java.util.Date`; both are noted in the
  source and out of scope for a mechanical JDK/framework migration.
- Neither service needed `--add-opens`, so there is nothing to remove later.
