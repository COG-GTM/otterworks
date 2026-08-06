# Java 17 / Spring Boot 3.2 migration

Every JVM service in the repo is now on **Java 17** — build file, Dockerfile base images and
CI pin all agree — and every Spring Boot service is on **3.2.x**. The inventory this was
derived from is `docs/java17-migration-intake.yaml`.

| service | build | Java before → after | framework before → after | class |
|---|---|---|---|---|
| `report-service` | Maven | 8 → 17 | Spring Boot 2.5.14 → 3.2.5 | migrate |
| `legacy-portal` | Maven | 11 → 17 | Spring Boot 2.7.18 → 3.2.5 | migrate |
| `auth-service` | Gradle | 17 | Spring Boot 3.2.4 | verify |
| `notification-service` | Gradle (kts) | 17 (`jvmToolchain(17)`) | Ktor 2.3.9 / Kotlin 1.9.23 | jdk-only |
| `analytics-service` | sbt | 17 | Akka HTTP 10.5.3 / Scala 3.4.0 | jdk-only |

`frontend/client-app/mobile/android` is the Capacitor Android shell, not a backend JVM
service; its Gradle build is driven by AGP and requires JDK 21 per the repo blueprint, so it
is out of scope.

## report-service (Java 8 / Boot 2.5.14 → Java 17 / Boot 3.2.5)

**OpenRewrite** (`rewrite-spring:RELEASE`, `UpgradeSpringBoot_3_2`) — 21 files, +252/−290:

- Boot parent bump; `java.version` → 17 and removal of `maven.compiler.source/target`.
- `javax.persistence` / `javax.validation` / `javax.transaction` → `jakarta.*`.
- SpringFox → springdoc-openapi 2.x, both the dependency swap and the annotations
  (`@Api`→`@Tag`, `@ApiOperation`→`@Operation`, `@ApiModelProperty`→`@Schema`).
- `WebSecurityConfigurerAdapter` → a `SecurityFilterChain` bean with
  `authorizeHttpRequests` / `requestMatchers`.
- JUnit 4 → Jupiter across all 5 test classes, including the `assertX(msg, cond)` →
  `assertX(cond, msg)` argument reordering.
- Apache HttpClient 4 → 5; commons-lang → commons-lang3; `!isPresent()` → `isEmpty()`;
  Dockerfile runtime tag.

**Hand-fixed** (what the recipe left broken or incomplete):

- Parent pinned to 3.2.5 (the recipe picked the newest 3.2.x, 3.2.12).
- The recipe converted the tests to Jupiter but left the `junit-jupiter` **exclusion** on
  `spring-boot-starter-test`, so nothing compiled — exclusion dropped.
- HttpClient 5 moved the read timeout off `RequestConfig`; reconfigured via `SocketConfig`.
- Spring Security 6 `xssProtection` takes a `headerValue` rather than a boolean.
- Added the springdoc `OpenAPI` bean (SpringFox's `Docket` has no equivalent).
- Apache POI 4.1.2 → 5.2.5, commons-io 2.6 → 2.15.1, Guava 28.0 → 33.1.0 (all shipped
  `javax` transitively or break under JDK 17's strong encapsulation).
- `@JdbcTypeCode(SqlTypes.LONGVARCHAR)` on the `@Lob String` column: Hibernate 6 otherwise
  maps it to a Postgres `oid` and the column silently breaks at runtime.
- Builder image → `maven:3.9-eclipse-temurin-17`, runtime → `eclipse-temurin:17-jre-jammy`.
- CI: `ci.yml` `report-service` job and `docker-build.yml` `report-service-tests` job →
  `java-version: '17'`.

`mvn -B clean verify` on JDK 17: **BUILD SUCCESS, 44 tests → 44 tests**, all green. No tests
deleted or weakened. No trailing-slash breakage (no route or test relied on one). No
`--add-opens` needed. No `spring-boot-properties-migrator` warnings.

## legacy-portal (Java 11 / Boot 2.7.18 → Java 17 / Boot 3.2.5)

Coming from 11 rather than 8, this was the smaller half: no JAXB/Nashorn removals, no
reflective-access failures, no Spring Security (the service has none), no `@Lob`.

**OpenRewrite** handled `javax.persistence` / `javax.validation` → `jakarta.*` across 6
files, the parent bump, `java.version` 17, and the runtime Docker image.

**Hand-fixed**: parent pinned to 3.2.5 (recipe chose 3.2.12); removed the redundant
`maven.compiler.source/target`; the **builder** image `maven:3.9-eclipse-temurin-11` → `-17`,
which the recipe missed; reverted an out-of-scope `application.yml` profile split the recipe
introduced. CI: `legacy-portal` and `legacy-portal-tests` jobs → `java-version: '17'`.

`mvn -B clean verify` on JDK 17: **BUILD SUCCESS, 13 tests → 13 tests**, all green.
`spring-boot-properties-migrator` was added temporarily and logged nothing, then removed.

## Already compliant (confirmed, not changed)

Each was checked on all three axes and compiled locally on JDK 17:

- **auth-service** — Boot 3.2.4, `sourceCompatibility = VERSION_17`, `gradle:8.6-jdk17` /
  `eclipse-temurin:17-jre-jammy`, CI `'17'`. `gradle compileJava` green.
- **notification-service** — Kotlin/Ktor, `jvmToolchain(17)`, `gradle:8.6-jdk17` /
  `eclipse-temurin:17-jre-jammy`, CI `'17'`. `gradle compileKotlin` green.
- **analytics-service** — Scala 3 / sbt, `sbtscala/scala-sbt:eclipse-temurin-…-17.0.10` /
  `eclipse-temurin:17-jre-jammy`, CI `'17'`. `sbt compile` green.

## Sweeps

All three return nothing on this branch:

```bash
grep -rn 'import javax\.' --include='*.java' --include='*.kt' . \
  | grep -v 'javax\.\(crypto\|sql\|net\|naming\|security\|imageio\|xml\.namespace\)'
grep -rn 'temurin-8\|temurin:8\|temurin-11\|temurin:11\|openjdk:8\|openjdk:11' --include=Dockerfile* -r .
grep -rn "java-version: '\(8\|11\)'" .github/workflows/
```

## Follow-ups

- **iText 5.5.13.3** (AGPL, pre-license-change) is still there. It runs fine on JDK 17 so it
  was left alone; migrating to OpenPDF or iText 7 is its own change.
- `auth-service` stays on Boot **3.2.4** rather than 3.2.5 — it was already compliant, and
  bumping a `verify` service is out of scope for this migration.
- The local dev box has neither Maven nor Gradle on `PATH` and the wrapper jars are
  gitignored, so `./gradlew` fails with `GradleWrapperMain not found`. Worth folding
  `maven` + a Gradle distribution into `.devin/blueprint.yaml`.
