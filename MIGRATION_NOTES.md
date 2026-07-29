# Java 17 / Spring Boot 3.2 Migration Notes

Every JVM service in this repo now targets **Java 17** — build file, Dockerfile base
images, and CI `java-version` pin all agree. Both Spring Boot services that were behind
are on **Boot 3.2.5**.

Inventory that drove this work: [`docs/java17-migration-intake.yaml`](docs/java17-migration-intake.yaml).

| Service | Build | Java (before → after) | Framework (before → after) | Class |
|---|---|---|---|---|
| `report-service` | Maven | 8 → 17 | Spring Boot 2.5.14 → 3.2.5 | migrate |
| `legacy-portal` | Maven | 11 → 17 | Spring Boot 2.7.18 → 3.2.5 | migrate |
| `auth-service` | Gradle | 17 (unchanged) | Spring Boot 3.2.4 (unchanged) | verify |
| `notification-service` | Gradle KTS | 17 (`jvmToolchain(17)`, unchanged) | Ktor / Kotlin | jdk-only |
| `analytics-service` | sbt | 17 (unchanged) | Akka HTTP / Scala 3 | jdk-only |

Non-JVM services (`api-gateway` Go, `file-service` Rust, `search-service`,
`audit-service`, `frontend/*`) are out of scope and untouched.

## report-service (Java 8 → 17, Boot 2.5.14 → 3.2.5)

Started from `OpenRewrite org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2`
(`rewrite-spring:RELEASE`), then hand-fixed the remainder.

**OpenRewrite handled**
- Boot parent bump, `<java.version>` 1.8 → 17, `maven.compiler.source/target` → `<release>`.
- `javax.persistence` / `javax.validation` / `javax.transaction` / `javax.servlet` → `jakarta.*`.
- `WebSecurityConfigurerAdapter` → `SecurityFilterChain` bean; `authorizeRequests()`/`antMatchers()`
  → `authorizeHttpRequests()`/`requestMatchers()`; lambda-style `csrf`/`headers`/`sessionManagement`.
- SpringFox Swagger 2 annotations → OpenAPI 3 (`@Tag`, `@Operation`, `@ApiResponse`, `@Schema`).
- JUnit 4 → JUnit 5 (`@RunWith(SpringRunner.class)` removed, `org.junit.Test` → `org.junit.jupiter.api.Test`).
- Apache HttpClient 4 → 5 imports (`org.apache.hc.*`).

**Hand-fixed after the recipe**
- Pinned the Boot parent to **3.2.5** (the recipe picked the latest 3.2.x, 3.2.12).
- Dependencies: SpringFox → `springdoc-openapi-starter-webmvc-ui` 2.5.0; iText 5 (AGPL) →
  **OpenPDF** 1.3.35; POI 4.1.2 → 5.2.5; commons-lang 2 → commons-lang3; commons-io 2.15.1;
  Guava 33.1.0-jre; `httpclient5`. Removed the explicit `javax.servlet-api` dependency
  (the Boot 3 web starter brings `jakarta.servlet-api`). Mockito/JUnit versions come from the
  Boot 3.2 BOM — no explicit pins, and the old JUnit 5 exclusion is gone.
- OpenPDF API: `com.itextpdf.text.*` → `com.lowagie.text.*`, and OpenPDF uses `java.awt.Color`
  rather than iText 5's `BaseColor` (`Font.FontFamily.HELVETICA` → `Font.HELVETICA`).
- HttpClient 5 dropped the request-factory read timeout: the socket timeout now lives on the
  connection manager (`SocketConfig.setSoTimeout`) in `AppConfig`.
- Spring Security 6.2 removed `xssProtection().block(boolean)` →
  `headerValue(XXssProtectionHeaderWriter.HeaderValue.ENABLED_MODE_BLOCK)`; permit-list updated
  from the SpringFox paths (`/v2/api-docs`, `/swagger-resources`) to the springdoc ones
  (`/v3/api-docs/**`, `/swagger-ui/**`).
- `SwaggerConfig` now exposes an `OpenAPI` bean (the recipe left a `Docket`-less class with an
  orphaned `Info` builder).
- Removed `spring.mvc.pathmatch.matching-strategy=ant-path-matcher` — that was the SpringFox
  workaround for Boot 2.6+, and it is actively harmful with Boot 3's `PathPatternParser`.
- **Security 6 error dispatch:** Security 5 let unmatched requests through; Security 6's
  `AuthorizationFilter` denies them *and* runs on the ERROR dispatch, so `/error` was denied and
  every 400/404 came back as a bodiless 403. Restored the Security 5 behaviour with a final
  `.anyRequest().permitAll()` (caught by the runtime check, not by any test).
- **Hibernate 6:** `Report.errorMessage` is a `@Lob String`, which Hibernate 6 maps to a Postgres
  `oid` (the column silently reads back as a number). Added `@JdbcTypeCode(SqlTypes.LONGVARCHAR)`.
- Dockerfile: `maven:3.8.7-eclipse-temurin-8` → `maven:3.9-eclipse-temurin-17`, runtime
  `eclipse-temurin:17-jre-jammy`.

**Tests:** 44 before → **44 after**, all green on JDK 17 (`mvn -B clean test`). No `--add-opens`
was needed.

## legacy-portal (Java 11 → 17, Boot 2.7.18 → 3.2.5)

Same recipe. Coming from 11 there was much less to do — no JAXB/Nashorn work, no `--add-opens`.

**OpenRewrite handled:** Boot parent + `java.version`, `javax.persistence`/`javax.validation` →
`jakarta.*` across the three bounded contexts, and the runtime image in the Dockerfile.

**Hand-fixed:** pinned the parent to 3.2.5; bumped the *builder* stage
(`maven:3.9-eclipse-temurin-11` → `-17`, which the recipe left alone); restored the `postgres`
profile document in `application.yml`, which the recipe's YAML rewrite dropped.

**Tests:** 13 before → **13 after**, all green on JDK 17.

## Services confirmed already compliant

- `auth-service` — Gradle, `sourceCompatibility = JavaVersion.VERSION_17`, Boot 3.2.4,
  `gradle:8.6-jdk17` / `eclipse-temurin:17-jre-jammy`, CI pinned to 17. No change.
- `notification-service` — Kotlin/Ktor, `jvmToolchain(17)`, JDK 17 images, CI 17. No change.
- `analytics-service` — Scala 3 / sbt, Temurin 17 builder and runtime, CI 17. No change.

## Repo-wide checks

All three straggler sweeps return nothing:

```bash
grep -rn 'import javax\.' --include='*.java' --include='*.kt' . | grep -v 'javax\.\(crypto\|sql\|net\|naming\|security\|imageio\|xml\.namespace\)'
grep -rn 'temurin-8\|temurin:8\|temurin-11\|temurin:11\|openjdk:8\|openjdk:11' --include=Dockerfile* -r .
grep -rn "java-version: '\(8\|11\)'" .github/workflows/
```

CI (`ci.yml`, `docker-build.yml`) now pins `java-version: '17'` with `cache: maven` for both
Maven services.

## Follow-ups (not done here — out of scope for a version migration)

- `report-service` still uses `java.util.Date` + `SimpleDateFormat`, `RestTemplate`, OpenCSV 4.6,
  and manual DTO mapping. All are behaviour-preserving refactors, deliberately not mixed in.
- `report-service` security filter chain still permits everything under `/api/v1/reports/**`
  (pre-existing `TODO: Add JWT validation`).
- No service was moved to Java 21; `frontend/client-app/mobile` Android already builds at 21.
- **Trailing slashes:** Spring Framework 6 no longer matches `GET /api/v1/reports/` to
  `/api/v1/reports` — that URL is now 404 where it was 200 on `main`. No caller in this repo uses
  the trailing-slash form; accepted as the framework default rather than re-enabled via
  `PathPatternParser`/`setUseTrailingSlashMatch`.
- Boot 3.2 deprecates `spring.jpa.hibernate.ddl-auto=update` style schema management in favour of
  migrations (Flyway/Liquibase) — unchanged here, still `update`.
