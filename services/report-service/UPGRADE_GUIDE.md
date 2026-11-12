# Report Service Upgrade Guide -- Java 8 to Java 21

This document is the Java 21 baseline and blocker inventory for `services/report-service`
(migration plan step `s1.3`). It records how the service builds and tests on Java 8 today,
what was measured on JDK 21, and each upgrade axis with the exact files, imports and
annotations that change. Later phases compare against the baseline below.

Target end state: **Java 21 (LTS)** on **Spring Boot 3.x** (3.5.x is the newest 3.x line;
4.x is the forward option), reached via Spring Boot 2.7.18 as the Java 21 stepping stone.

---

## Baseline (measured on `main`)

| Item | Value today |
|---|---|
| Spring Boot parent | **2.5.15** (the pom comment still says 2.5.14) |
| Compiler | `maven-compiler-plugin` 3.8.1, `<source>`/`<target>` 1.8 |
| Tests | `maven-surefire-plugin` 2.22.2, JUnit 4.13.2 (Jupiter excluded from `spring-boot-starter-test`) |
| Container | `maven:3.8.7-eclipse-temurin-8` builder, `eclipse-temurin:8-jre` runtime (`Dockerfile`) |
| CI | `ci.yml` job `report-service` and `docker-build.yml` job `report-service-tests` use `setup-java` `java-version: '8'` |
| Dependency harness | `security/deps/modules.yaml` runs report-service on **JDK 11** (recorded `script:` lookup needs Nashorn) |

`mvn -B test` results (7 test classes, 50 tests, 0 failures, 0 errors, 1 skipped):

| Run | JDK | Bytecode | Result |
|---|---|---|---|
| Baseline | 8 (`java-8-openjdk`) | 8 | 50 run, 0 failed, 1 skipped -- BUILD SUCCESS |
| Runtime probe | 21.0.12 | 8 (pom unchanged) | 50 run, 0 failed, 1 skipped -- BUILD SUCCESS |
| Compile probe | 21.0.12 | 21 (`source`/`target` set to 21 in a scratch copy) | 50 run, 0 failed, 1 skipped -- BUILD SUCCESS |

The skipped test is `DependencyTranscriptEmitterTest`, which only runs when the
`security/deps` harness passes `-Dow.deps.cases` / `-Dow.deps.observed`.
Per class: `ReportControllerIntegrationTest` 16, `ExcelReportGeneratorTest` 9,
`ReportServiceTest` 8, `CsvReportGeneratorTest` 6, `PdfReportGeneratorTest` 5,
`ReportHeaderRendererTest` 5, `DependencyTranscriptEmitterTest` 1 (skipped).

So the current stack compiles and its suite passes on JDK 21, but Spring Boot 2.5 is only
documented as compatible up to Java 18 (2.7.18 is documented up to Java 21). A green suite
is not support: the test suite does not exercise Hibernate lazy proxies or Swagger UI.

---

## JDK API findings (`jdeps` on the built jar, JDK 21)

Commands (run against the exploded `target/report-service.jar`):

```bash
jdeps --jdk-internals --multi-release 21 BOOT-INF/classes
for j in BOOT-INF/lib/*.jar; do jdeps --jdk-internals --multi-release 21 --ignore-missing-deps "$j"; done
jdeprscan --release 21 --for-removal --class-path 'BOOT-INF/lib/*' BOOT-INF/classes
```

| Where | JDK internal used | Status on 21 | Blocks Java 21? |
|---|---|---|---|
| Application classes (`com.otterworks.report.*`) | none | -- | No (jdeprscan: no for-removal APIs either) |
| `logback-classic` 1.2.12 | `sun.reflect.Reflection` | **removed** | No: only used for packaging data, which logback guards and leaves off by default; logback 1.4+/1.5 (Boot 3) drops it |
| `guava` 28.0-jre | `sun.misc.Unsafe` (`jdk.unsupported`) | present | No |
| `spring-core` 5.3.27 (objenesis) | `sun.misc.Unsafe` | present | No |
| `aspectjweaver` 1.9.7 | `sun.misc.Unsafe` | present | No |

Removed-from-JDK features that matter here:

- **Nashorn** (removed in JDK 15): Commons Text's `script:` lookup has no `javascript`
  engine. Measured with commons-text 1.9: `${script:javascript:3+4}` resolves to `7` on
  JDK 11 and throws `IllegalArgumentException: Error in script engine [javascript]` on JDK 17
  and 21. See Axis 12.
- No `javax.xml.bind`, `javax.annotation`, `javax.activation` or other removed Java EE
  modules are imported by the code; the Boot 2.5 BOM already supplies the
  `jakarta.*-api` 1.x/2.x jars (which still use `javax.*` packages).

---

## `javax.*` usage

| Package | Imports | Files |
|---|---|---|
| `javax.persistence` | 11 | `model/Report.java` |
| `javax.validation` | 4 | `model/Report.java`, `model/ReportRequest.java`, `controller/ReportController.java` |
| `javax.transaction` | 1 | `service/ReportService.java` |
| `javax.servlet` | 0 imports | explicit `javax.servlet:javax.servlet-api:4.0.1` (`provided`) in `pom.xml`; SpringFox also pulls `javax.servlet` APIs |

None of these block Java 21 itself (they run on JDK 21 today). All of them block
**Spring Boot 3** (Jakarta EE 9+), see Axis 3.

---

## Library inventory: current -> Java 21 target

"Required for Java 21" means the module cannot run or be supported on Java 21 without it.
"Required for Boot 3" means it must move in the Spring Boot 3 / jakarta step. Latest
versions were read from Maven Central metadata; bytecode levels were read from the jars.

| Library | Current | Runs on Java 21 today? | Java 21 target | Required for Java 21 | Required for Boot 3 |
|---|---|---|---|---|---|
| Spring Boot (parent) | 2.5.15 | Tests pass, but officially compatible only up to Java 18 | **2.7.18** (compatible up to 21), then 3.5.x (or 4.x) | **Required** (2.7.18 minimum) | -- |
| `javax.servlet-api` | 4.0.1 (provided) | Yes | Remove (Boot 3 starter-web brings `jakarta.servlet-api`) | Optional | **Required** |
| SpringFox (`springfox-boot-starter`) | 3.0.0 (last release, 2020) | Yes on Boot 2.5-2.7 with `ant-path-matcher` workaround | springdoc-openapi: `springdoc-openapi-ui` 1.8.0 on Boot 2.7, `springdoc-openapi-starter-webmvc-ui` 2.8.x on Boot 3 (3.x line for Boot 4) | Optional | **Required** (javax, dead project) |
| Apache POI | 4.1.2 | Yes (Excel tests pass) | 5.4.1 / 5.5.1 (Java 8 bytecode); 6.0.0 needs Java 17 | Optional | Optional |
| iText | 5.5.13.3 (AGPL, EOL) | Yes (PDF tests pass) | OpenPDF 2.0.x (`com.lowagie`, Java 17 bytecode); OpenPDF 3.x renames packages to `org.openpdf`; or iText 9 (commercial/AGPL, rewrite) | Optional | Optional (licence) |
| commons-lang | 2.6 (EOL) | Yes | `org.apache.commons:commons-lang3` 3.18+ (latest 3.22.0) | Optional | Optional |
| commons-io | 2.6 | Yes | 2.16+ (latest 2.22.0, Java 8 bytecode) | Optional | Optional |
| Guava | 28.0-jre | Yes (`sun.misc.Unsafe` only) | 33.x-jre (latest 33.8.0) | Optional | Optional |
| Apache HttpClient | 4.5.13 | Yes | `httpclient5` 5.x (Spring Framework 6's `HttpComponentsClientHttpRequestFactory` only supports HttpClient 5) | Optional | **Required** |
| OpenCSV | 4.6 | Yes (CSV tests pass) | 5.9+ (latest 5.12.0) | Optional | Optional |
| commons-text | 1.9 (CVE-2022-42889) | Runs, but `script:` lookup cannot resolve on 15+ (Nashorn removed) | 1.10.0+ (latest 1.15.0) | Optional (security: **required**, see Axis 12) | Optional |
| JUnit | 4.13.2 | Yes | JUnit Jupiter 5.x (Boot 3 BOM) | Optional | Optional (Boot 3 still runs vintage); required if moving to Boot 4 / JUnit 6 |
| Mockito | 3.12.4 (explicit), `mockito-junit-jupiter` 3.9.0 transitive | Yes -- **no test imports Mockito** | 5.x (Boot 3 BOM), or drop the explicit dependency | Optional | Optional |
| `maven-compiler-plugin` | 3.8.1 | Yes | 3.13+ with `<release>21</release>` | Optional | Optional |
| `maven-surefire-plugin` | 2.22.2 | Yes | 3.x | Optional | Optional |
| Docker base images | `maven:3.8.7-eclipse-temurin-8`, `eclipse-temurin:8-jre` | n/a | `maven:3.9-eclipse-temurin-21`, `eclipse-temurin:21-jre` | **Required** | -- |
| CI `setup-java` | `'8'` (`ci.yml`, `docker-build.yml`) | n/a | `'21'` | **Required** | -- |
| `security/deps/modules.yaml` JDK | 11 | n/a | 21 once the module targets 21 (see Axis 12) | **Required** | -- |

---

## Plan conflicts found while verifying

1. **springdoc before Spring Boot 3** (plan step s3.1 runs before s3.4): springdoc 2.x
   (`springdoc-openapi-starter-webmvc-ui`) requires Spring Boot 3 / jakarta. On Boot 2.7 the
   replacement must be `org.springdoc:springdoc-openapi-ui:1.8.0`, then swapped for the 2.x
   starter in the Boot 3 step. The annotation migration (Axis 5) is identical for both.
2. **commons-text after the Java 21 switch** (s3.3 after s2.2): the `security/deps` harness
   measures report-service on JDK 11 and its recorded baseline expects
   `${script:javascript:3+4}` -> `7`, which only reproduces with Nashorn (JDK <= 14). Once
   the pom targets 21 the module cannot compile on JDK 11 (harness exit 2, "unmeasured"), and
   on JDK 21 the attack baseline cannot be reproduced. Either run s3.3 before s2.2, or
   repoint the harness to JDK 21 (s4.2) before s3.3 and accept that the `script:` attack case
   errors rather than resolves on 21.
3. **commons-text on `main`**: the repo's `dependency-cve-remediation` skill states that
   `main` deliberately keeps the vulnerable 1.9 pin as the exercise's before-state and that
   remediations land on a branch, never merged to `main`. Merging s3.3 to `main` conflicts
   with that policy and needs an explicit decision.
4. **Spring Boot 2.5 already passes on Java 21 bytecode**: s2.1 (Boot 2.7) is still needed
   for official Java 21 support, but it is not what makes the suite green.

---

## Overview

| # | Axis | From | To | Files Affected | Required for Java 21 |
|---|------|------|----|----------------|---|
| 1 | Java version | 1.8 | 21 | `pom.xml` | Yes |
| 2 | Spring Boot | 2.5.15 | 2.7.18, then 3.5.x | `pom.xml`, `SecurityConfig.java` | 2.7.18: yes; 3.x: no |
| 3 | javax to jakarta | `javax.*` | `jakarta.*` | `Report.java`, `ReportRequest.java`, `ReportController.java`, `ReportService.java`, `pom.xml` | No (Boot 3) |
| 4 | JUnit 4 to JUnit 5 | JUnit 4 | JUnit 5 / Jupiter | All test files | No |
| 5 | SpringFox to springdoc | SpringFox 3.0.0 | springdoc-openapi 1.8.0 (Boot 2.7) / 2.x (Boot 3) | `SwaggerConfig.java`, `ReportController.java`, model classes | No (Boot 3) |
| 6 | iText 5 to OpenPDF / iText | iText 5.5.13.3 | OpenPDF 2.0.x or iText 9 | `PdfReportGenerator.java` | No |
| 7 | Commons Lang 2 to 3 | `commons-lang:commons-lang:2.6` | `org.apache.commons:commons-lang3:3.18+` | `ReportDateUtils.java`, `PdfReportGenerator.java`, `ExcelReportGenerator.java`, `ReportDataFetcher.java` | No |
| 8 | Commons IO | 2.6 | 2.16+ | `pom.xml`, `ReportController.java` | No |
| 9 | Guava | 28.0-jre | 33+ | `pom.xml`, `ReportDataFetcher.java` | No |
| 10 | Apache POI | 4.1.2 | 5.4+ | `pom.xml`, `ExcelReportGenerator.java` | No |
| 11 | Mockito | 3.12.4 | 5.x | `pom.xml` | No |
| 12 | Commons Text | 1.9 | 1.10.0+ | `pom.xml`, `ReportHeaderRenderer.java`, `security/deps` | No (security) |
| 13 | Apache HttpClient | 4.5.13 | httpclient5 5.x | `pom.xml`, `AppConfig.java` | No (Boot 3) |
| 14 | OpenCSV | 4.6 | 5.9+ | `pom.xml`, `CsvReportGenerator.java` | No |
| 15 | Build, container, CI | JDK 8 images / jobs | JDK 21 | `Dockerfile`, `ci.yml`, `docker-build.yml`, `security/deps/modules.yaml` | Yes |

---

## Axis 1 -- Java Version (1.8 to 21)

### What changes

**File:** `pom.xml`

```xml
<!-- BEFORE -->
<java.version>1.8</java.version>
<maven.compiler.source>1.8</maven.compiler.source>
<maven.compiler.target>1.8</maven.compiler.target>

<!-- AFTER -->
<java.version>21</java.version>
<maven.compiler.release>21</maven.compiler.release>
```

Also update the `maven-compiler-plugin` configuration block (and bump the plugin to 3.13+):

```xml
<!-- BEFORE -->
<source>1.8</source>
<target>1.8</target>

<!-- AFTER -->
<release>21</release>
```

### How to verify

```bash
mvn compile
java -version   # must report 21
```

All source files must compile without errors under Java 21. Measured: they already do, and
`mvn -B test` passes (50 run, 1 skipped) with bytecode 21 on Spring Boot 2.5.15.

---

## Axis 2 -- Spring Boot (2.5.15 to 2.7.18, then 3.x)

Step 1 (required for Java 21): move the parent to `2.7.18`, the last 2.x release and the
first line documented as compatible with Java 21. It brings Hibernate 5.6.15, Byte Buddy
1.12.23 and Spring Framework 5.3.31. Keep `spring.mvc.pathmatch.matching-strategy=ant-path-matcher`
while SpringFox is present. Step 2 (Boot 3) is shown below.

### What changes

**File:** `pom.xml`

```xml
<!-- BEFORE -->
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>2.5.15</version>
</parent>

<!-- AFTER -->
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.5.x</version>  <!-- newest 3.x line; 3.2+ is the minimum for Java 21 -->
</parent>
```

Spring Boot 3.x requires Java 17+ (Axis 1) and jakarta namespace (Axis 3).

### Additional changes

- **`SecurityConfig.java`**: `WebSecurityConfigurerAdapter` is removed in Spring Security 6.
  Replace the `extends WebSecurityConfigurerAdapter` / `configure(HttpSecurity)` pattern with
  a `@Bean SecurityFilterChain` method:

  ```java
  // BEFORE
  public class SecurityConfig extends WebSecurityConfigurerAdapter {
      @Override
      protected void configure(HttpSecurity http) throws Exception { ... }
  }

  // AFTER
  public class SecurityConfig {
      @Bean
      public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
          http ...
          return http.build();
      }
  }
  ```

- **`SecurityConfig.java`**: Replace `antMatchers(...)` with `requestMatchers(...)`,
  and `authorizeRequests()` with `authorizeHttpRequests()`.

- **`application-test.properties`**: The property
  `spring.mvc.pathmatch.matching-strategy=ant-path-matcher` can be removed once
  SpringFox is replaced with springdoc (Axis 5).

### How to verify

```bash
mvn spring-boot:run       # application starts without errors
mvn test                  # all tests pass
curl http://localhost:8080/health   # returns {"status":"healthy",...}
```

---

## Axis 3 -- javax to jakarta

### What changes

Every `javax.*` import in the source tree must be renamed to `jakarta.*`. This is
required by Spring Boot 3.x / Jakarta EE 9+.

**Files affected (and the specific imports):**

| File | javax import | jakarta replacement |
|------|-------------|---------------------|
| `model/Report.java` | `javax.persistence.Column` | `jakarta.persistence.Column` |
| `model/Report.java` | `javax.persistence.Entity` | `jakarta.persistence.Entity` |
| `model/Report.java` | `javax.persistence.EnumType` | `jakarta.persistence.EnumType` |
| `model/Report.java` | `javax.persistence.Enumerated` | `jakarta.persistence.Enumerated` |
| `model/Report.java` | `javax.persistence.GeneratedValue` | `jakarta.persistence.GeneratedValue` |
| `model/Report.java` | `javax.persistence.GenerationType` | `jakarta.persistence.GenerationType` |
| `model/Report.java` | `javax.persistence.Id` | `jakarta.persistence.Id` |
| `model/Report.java` | `javax.persistence.Lob` | `jakarta.persistence.Lob` |
| `model/Report.java` | `javax.persistence.Table` | `jakarta.persistence.Table` |
| `model/Report.java` | `javax.persistence.Temporal` | `jakarta.persistence.Temporal` |
| `model/Report.java` | `javax.persistence.TemporalType` | `jakarta.persistence.TemporalType` |
| `model/Report.java` | `javax.validation.constraints.NotNull` | `jakarta.validation.constraints.NotNull` |
| `model/ReportRequest.java` | `javax.validation.constraints.NotBlank` | `jakarta.validation.constraints.NotBlank` |
| `model/ReportRequest.java` | `javax.validation.constraints.NotNull` | `jakarta.validation.constraints.NotNull` |
| `controller/ReportController.java` | `javax.validation.Valid` | `jakarta.validation.Valid` |
| `service/ReportService.java` | `javax.transaction.Transactional` | `jakarta.transaction.Transactional` |

**Also in `pom.xml`:** Remove the explicit `javax.servlet-api` dependency:

```xml
<!-- REMOVE this block entirely -->
<dependency>
    <groupId>javax.servlet</groupId>
    <artifactId>javax.servlet-api</artifactId>
    <version>4.0.1</version>
    <scope>provided</scope>
</dependency>
```

Spring Boot 3.x starter-web already includes `jakarta.servlet-api`.

### How to verify

```bash
# No javax imports should remain (except javax.sql which is still valid in Java 21)
grep -rn "import javax\." src/main/java/ | grep -v "javax.sql"
# Should return zero results

mvn compile   # compiles cleanly
mvn test      # all tests pass
```

---

## Axis 4 -- JUnit 4 to JUnit 5

### What changes

**Files affected:** All files under `src/test/java/`

| JUnit 4 | JUnit 5 replacement |
|---------|---------------------|
| `import org.junit.Test` | `import org.junit.jupiter.api.Test` |
| `import org.junit.runner.RunWith` | Remove entirely |
| `import org.springframework.test.context.junit4.SpringRunner` | Remove entirely |
| `@RunWith(SpringRunner.class)` | Remove (not needed with `@SpringBootTest` in JUnit 5) |

**In `pom.xml`:**

```xml
<!-- REMOVE the JUnit 4 dependency -->
<dependency>
    <groupId>junit</groupId>
    <artifactId>junit</artifactId>
    <version>4.13.2</version>
    <scope>test</scope>
</dependency>

<!-- REMOVE the JUnit 5 exclusion from spring-boot-starter-test -->
<exclusions>
    <exclusion>
        <groupId>org.junit.jupiter</groupId>
        <artifactId>junit-jupiter</artifactId>
    </exclusion>
</exclusions>

<!-- ADD JUnit 5 (or rely on spring-boot-starter-test which includes it) -->
<dependency>
    <groupId>org.junit.jupiter</groupId>
    <artifactId>junit-jupiter</artifactId>
    <scope>test</scope>
</dependency>
```

Update the `maven-surefire-plugin` to 3.x to pick up Jupiter automatically:

```xml
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-surefire-plugin</artifactId>
    <version>3.5.x</version>  <!-- newest 3.x line; 3.2+ is the minimum for Java 21 -->
</plugin>
```

### Annotation mapping (per test file)

**`ReportServiceTest.java`** (and all new test files):

```java
// BEFORE
import org.junit.Test;
import org.junit.runner.RunWith;
import org.springframework.test.context.junit4.SpringRunner;

@RunWith(SpringRunner.class)
@SpringBootTest
public class ReportServiceTest { ... }

// AFTER
import org.junit.jupiter.api.Test;

@SpringBootTest
public class ReportServiceTest { ... }
```

### How to verify

```bash
mvn test
# All tests discovered and executed by the Jupiter engine
# No "vintage" engine warnings in output
```

---

## Axis 5 -- SpringFox to springdoc-openapi

### What changes

**Files affected:**

- `config/SwaggerConfig.java` -- delete or rewrite entirely
- `controller/ReportController.java` -- replace annotations
- `model/Report.java` -- replace annotations
- `model/ReportRequest.java` -- replace annotations
- `model/ReportResponse.java` -- replace annotations

**In `pom.xml`:**

```xml
<!-- REMOVE -->
<dependency>
    <groupId>io.springfox</groupId>
    <artifactId>springfox-boot-starter</artifactId>
    <version>${springfox.version}</version>
</dependency>

<!-- ADD while still on Spring Boot 2.7 (javax) -->
<dependency>
    <groupId>org.springdoc</groupId>
    <artifactId>springdoc-openapi-ui</artifactId>
    <version>1.8.0</version>
</dependency>

<!-- REPLACE with this in the Spring Boot 3 step (jakarta) -->
<dependency>
    <groupId>org.springdoc</groupId>
    <artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>
    <version>2.8.x</version>
</dependency>
```

**Annotation replacements:**

| SpringFox (old) | springdoc (new) |
|-----------------|-----------------|
| `@Api(tags = "...")` | `@Tag(name = "...")` |
| `@ApiOperation(value = "...")` | `@Operation(summary = "...")` |
| `@ApiResponse(code = 200, message = "...")` | `@ApiResponse(responseCode = "200", description = "...")` |
| `@ApiParam(value = "...")` | `@Parameter(description = "...")` |
| `@ApiModel(description = "...")` | `@Schema(description = "...")` |
| `@ApiModelProperty(value = "...")` | `@Schema(description = "...")` |

**Import replacements:**

| Old import | New import |
|-----------|-----------|
| `io.swagger.annotations.Api` | `io.swagger.v3.oas.annotations.tags.Tag` |
| `io.swagger.annotations.ApiOperation` | `io.swagger.v3.oas.annotations.Operation` |
| `io.swagger.annotations.ApiResponse` | `io.swagger.v3.oas.annotations.responses.ApiResponse` |
| `io.swagger.annotations.ApiResponses` | `io.swagger.v3.oas.annotations.responses.ApiResponses` |
| `io.swagger.annotations.ApiParam` | `io.swagger.v3.oas.annotations.Parameter` |
| `io.swagger.annotations.ApiModel` | `io.swagger.v3.oas.annotations.media.Schema` |
| `io.swagger.annotations.ApiModelProperty` | `io.swagger.v3.oas.annotations.media.Schema` |

**`config/SwaggerConfig.java`:** The entire `Docket` bean class can be deleted.
springdoc auto-configures from annotations. If custom metadata is needed, use
`application.properties`:

```properties
springdoc.api-docs.path=/v3/api-docs
springdoc.swagger-ui.path=/swagger-ui.html
```

### How to verify

```bash
mvn spring-boot:run
curl http://localhost:8080/v3/api-docs       # returns OpenAPI 3.0 JSON
# Open http://localhost:8080/swagger-ui.html  in a browser
```

---

## Axis 6 -- iText 5 to OpenPDF or iText 7

### What changes

**File:** `service/PdfReportGenerator.java`

**Option A -- OpenPDF (recommended, LGPL fork of iText 5):**

The API is nearly identical to iText 5. Only the Maven coordinates and some
package names change.

In `pom.xml`:

```xml
<!-- REMOVE -->
<dependency>
    <groupId>com.itextpdf</groupId>
    <artifactId>itextpdf</artifactId>
    <version>${itext.version}</version>
</dependency>

<!-- ADD -->
<dependency>
    <groupId>com.github.librepdf</groupId>
    <artifactId>openpdf</artifactId>
    <version>2.0.5</version>  <!-- 2.0.x keeps com.lowagie packages; 3.x renames them to org.openpdf -->
</dependency>
```

Import changes in `PdfReportGenerator.java`:

| Old import (iText 5) | New import (OpenPDF) |
|----------------------|---------------------|
| `com.itextpdf.text.BaseColor` | `com.lowagie.text.BaseColor` |
| `com.itextpdf.text.Chunk` | `com.lowagie.text.Chunk` |
| `com.itextpdf.text.Document` | `com.lowagie.text.Document` |
| `com.itextpdf.text.DocumentException` | `com.lowagie.text.DocumentException` |
| `com.itextpdf.text.Element` | `com.lowagie.text.Element` |
| `com.itextpdf.text.Font` | `com.lowagie.text.Font` |
| `com.itextpdf.text.FontFactory` | `com.lowagie.text.FontFactory` |
| `com.itextpdf.text.PageSize` | `com.lowagie.text.PageSize` |
| `com.itextpdf.text.Paragraph` | `com.lowagie.text.Paragraph` |
| `com.itextpdf.text.Phrase` | `com.lowagie.text.Phrase` |
| `com.itextpdf.text.pdf.PdfPCell` | `com.lowagie.text.pdf.PdfPCell` |
| `com.itextpdf.text.pdf.PdfPTable` | `com.lowagie.text.pdf.PdfPTable` |
| `com.itextpdf.text.pdf.PdfWriter` | `com.lowagie.text.pdf.PdfWriter` |

**Option B -- iText 9 (AGPL or commercial license):**

The API is completely different. Would require a full rewrite of `PdfReportGenerator.java`
using `PdfDocument`, `com.itextpdf.layout.Document`, `Table`, `Cell`, etc.

### How to verify

```bash
mvn test   # PdfReportGeneratorTest passes
# Inspect a generated PDF -- should open correctly in any PDF reader
```

---

## Axis 7 -- Commons Lang 2 to Commons Lang 3

### What changes

**Files affected:**

- `util/ReportDateUtils.java`
- `service/PdfReportGenerator.java`
- `service/ExcelReportGenerator.java`
- `service/ReportDataFetcher.java`

**In `pom.xml`:**

```xml
<!-- REMOVE -->
<dependency>
    <groupId>commons-lang</groupId>
    <artifactId>commons-lang</artifactId>
    <version>2.6</version>
</dependency>

<!-- ADD -->
<dependency>
    <groupId>org.apache.commons</groupId>
    <artifactId>commons-lang3</artifactId>
    <version>3.18.0</version>
</dependency>
```

**Import replacements (all files above):**

| Old import | New import |
|-----------|-----------|
| `org.apache.commons.lang.StringUtils` | `org.apache.commons.lang3.StringUtils` |
| `org.apache.commons.lang.time.DateFormatUtils` | `org.apache.commons.lang3.time.DateFormatUtils` |
| `org.apache.commons.lang.time.DateUtils` | `org.apache.commons.lang3.time.DateUtils` |

The API is compatible -- `StringUtils.isBlank`, `StringUtils.capitalize`,
`DateFormatUtils.formatUTC`, and `DateUtils.parseDate` / `DateUtils.addDays` all
exist in commons-lang3 with the same signatures.

### How to verify

```bash
mvn compile   # no import errors
mvn test      # all tests pass
grep -rn "org.apache.commons.lang\." src/main/java/ | grep -v "lang3"
# Should return zero results
```

---

## Axis 8 -- Commons IO (2.6 to 2.16+)

### What changes

**Files affected:** `pom.xml`, `controller/ReportController.java`

In `pom.xml`:

```xml
<!-- BEFORE -->
<commons-io.version>2.6</commons-io.version>

<!-- AFTER -->
<commons-io.version>2.16.1</commons-io.version>
```

No import changes needed. `org.apache.commons.io.FileUtils.readFileToByteArray` has
the same signature in 2.16. The upgrade addresses known CVEs in 2.6.

### How to verify

```bash
mvn dependency:tree | grep commons-io
# Should show commons-io:commons-io:jar:2.16.1
mvn test
```

---

## Axis 9 -- Guava (28 to 33+)

### What changes

**Files affected:** `pom.xml`, `service/ReportDataFetcher.java`

In `pom.xml`:

```xml
<!-- BEFORE -->
<guava.version>28.0-jre</guava.version>

<!-- AFTER -->
<guava.version>33.1.0-jre</guava.version>
```

No import changes needed for the APIs used (`CacheBuilder`, `CacheLoader`,
`LoadingCache`). They are stable in Guava 33.

Alternatively, consider replacing `com.google.common.cache.CacheBuilder` with
Caffeine (`com.github.ben-manes.caffeine:caffeine`) since Spring Boot uses
Caffeine by default. The migration would change:

```java
// BEFORE (Guava)
import com.google.common.cache.CacheBuilder;
import com.google.common.cache.CacheLoader;
import com.google.common.cache.LoadingCache;

CacheBuilder.newBuilder()
    .maximumSize(100)
    .expireAfterWrite(5, TimeUnit.MINUTES)
    .build(new CacheLoader<>() { ... });

// AFTER (Caffeine)
import com.github.benmanes.caffeine.cache.Caffeine;
import com.github.benmanes.caffeine.cache.LoadingCache;

Caffeine.newBuilder()
    .maximumSize(100)
    .expireAfterWrite(5, TimeUnit.MINUTES)
    .build(key -> Collections.emptyList());
```

### How to verify

```bash
mvn dependency:tree | grep guava
# Should show com.google.guava:guava:jar:33.1.0-jre
mvn test
```

---

## Axis 10 -- Apache POI (4.1.2 to 5.4+)

### What changes

**Files affected:** `pom.xml`, `service/ExcelReportGenerator.java`

In `pom.xml`:

```xml
<!-- BEFORE -->
<poi.version>4.1.2</poi.version>

<!-- AFTER -->
<poi.version>5.4.1</poi.version>
```

The APIs used in `ExcelReportGenerator.java` (`XSSFWorkbook`, `Sheet`, `Row`,
`CellStyle`, `Font`, `IndexedColors`, `CellRangeAddress`, etc.) are stable across
POI 4.x to 5.x. Some deprecated factory methods in POI 4 may produce warnings but
still compile.

Key differences to watch:

- `IndexedColors` is still available but some colors may render differently.
- `SXSSFWorkbook` (streaming) is recommended for large datasets.
- POI 5.x requires Java 8+ (already satisfied by Axis 1).

### How to verify

```bash
mvn dependency:tree | grep poi
# Should show org.apache.poi:poi:jar:5.4.1 and poi-ooxml:5.4.1
mvn test   # ExcelReportGeneratorTest passes
```

---

## Axis 11 -- Mockito (3.12 to 5.x)

### What changes

**Files affected:** `pom.xml`, all test files using Mockito

In `pom.xml`:

```xml
<!-- BEFORE -->
<dependency>
    <groupId>org.mockito</groupId>
    <artifactId>mockito-core</artifactId>
    <version>3.12.4</version>
    <scope>test</scope>
</dependency>

<!-- AFTER -->
<dependency>
    <groupId>org.mockito</groupId>
    <artifactId>mockito-core</artifactId>
    <version>5.11.0</version>
    <scope>test</scope>
</dependency>
```

For JUnit 5 integration, also add:

```xml
<dependency>
    <groupId>org.mockito</groupId>
    <artifactId>mockito-junit-jupiter</artifactId>
    <version>5.11.0</version>
    <scope>test</scope>
</dependency>
```

Mockito 5.x requires Java 11+. Since Axis 1 upgrades to Java 21, this is satisfied.

Note: no test under `src/test/java` imports Mockito today (tests use MockMvc and real
beans), so the explicit `mockito-core` 3.12.4 dependency can also simply be dropped and left
to the Spring Boot BOM.

Key changes in Mockito 5:

- Inline mock maker is the default (no more `mockito-inline` artifact needed).
- `@RunWith(MockitoJUnitRunner.class)` becomes `@ExtendWith(MockitoExtension.class)`.
- Stricter stubbing by default (unnecessary stubs cause test failure).

### How to verify

```bash
mvn test   # all tests pass with Mockito 5
```

---

## Axis 12 -- Commons Text (1.9 to 1.10.0+) and the default interpolator

**Security:** commons-text 1.9 is inside the CVE-2022-42889 ("Text4Shell") range
`[1.5, 1.10.0)` per `security/deps/advisory.yaml`; 1.10.0 is the nearest fixed version.
This is owned by its own migration step; it is recorded here, not changed.

**Java 21 behaviour, independent of the CVE fix:** `ReportHeaderRenderer.resolveConfigured()`
calls `StringSubstitutor.createInterpolator()`, the *default* interpolator, on
operator-editable text (`banner.footer` in `report-banner.properties`). In 1.9 that
interpolator includes the `script:` lookup, which evaluates through the JDK
`javax.script` JavaScript engine (Nashorn). Nashorn was removed in JDK 15, so on Java 21
a `${script:javascript:...}` token can never resolve, regardless of the commons-text version:

| JDK | commons-text 1.9, `${script:javascript:3+4}` |
|---|---|
| 11 | `7` (with Nashorn deprecation warning) |
| 17 | `IllegalArgumentException: Error in script engine [javascript] evaluating script [3+4]` |
| 21 | same `IllegalArgumentException` |

`base64Decoder:` and `const:` (used by the shipped footer) resolve identically on 11, 17
and 21. Consequences:

- A footer containing `script:` makes `footer()` throw on Java 21 instead of resolving.
  1.10.0+ removes `script:`, `dns:` and `url:` from the default interpolator, after which
  such a token is left verbatim.
- The `security/deps` baseline (`security/deps/expected/report-service.json`,
  `attack-script-lookup` -> `7`) only reproduces on JDK <= 14; the harness pins
  report-service to JDK 11 in `security/deps/modules.yaml`. Once the pom targets 21 the
  harness must move to JDK 21 and that case's expected outcome changes. See "Plan conflicts".

## Axis 13 -- Apache HttpClient 4.5 to HttpClient 5

`AppConfig.restTemplate()` builds `HttpComponentsClientHttpRequestFactory` from
`org.apache.http.impl.client.HttpClients` / `PoolingHttpClientConnectionManager`.
HttpClient 4.5.13 runs on Java 21, but Spring Framework 6 (Boot 3) only supports
HttpClient 5 in `HttpComponentsClientHttpRequestFactory`, so this is required in the
Boot 3 step:

```xml
<dependency>
    <groupId>org.apache.httpcomponents.client5</groupId>
    <artifactId>httpclient5</artifactId>
</dependency>
```

Package moves `org.apache.http.impl.client.*` -> `org.apache.hc.client5.http.impl.classic.*`
and `org.apache.http.impl.conn.PoolingHttpClientConnectionManager` ->
`org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager`.

## Axis 14 -- OpenCSV (4.6 to 5.9+)

`CsvReportGenerator` uses `CSVWriter`. OpenCSV 4.6 runs on Java 21 (CSV tests pass);
5.x is optional, keeps the `com.opencsv` package and `CSVWriter` API used here.

## Axis 15 -- Build plugins, container and CI

Required for Java 21:

- `Dockerfile`: `maven:3.8.7-eclipse-temurin-8` -> `maven:3.9-eclipse-temurin-21`,
  `eclipse-temurin:8-jre` -> `eclipse-temurin:21-jre`.
- `.github/workflows/ci.yml` (`report-service`) and `.github/workflows/docker-build.yml`
  (`report-service-tests`): `java-version: '8'` -> `'21'`.
- `security/deps/modules.yaml`: report-service JDK 11 -> 21 (see Axis 12).

Optional: `maven-compiler-plugin` 3.8.1 -> 3.13+ (`<release>21</release>`),
`maven-surefire-plugin` 2.22.2 -> 3.x. Both current versions work on JDK 21 (measured).

---

## Recommended Upgrade Order

1. **Spring Boot 2.7.18** (Axis 2, step 1) -- first line documented for Java 21
2. **Java 21** (Axis 1) plus Dockerfile/CI/harness JDK (Axis 15)
3. **SpringFox to springdoc 1.8.0** (Axis 5) -- javax-compatible on Boot 2.7
4. **JUnit 5 + Mockito 5** (Axes 4, 11)
5. **Commons Text 1.10.0+** (Axis 12) -- see the plan conflicts on harness JDK and `main`
6. **javax to jakarta** (Axis 3) + **Spring Boot 3.x** (Axis 2, step 2) + **HttpClient 5** (Axis 13)
   + springdoc 2.x starter -- one step; Boot 3 requires all of them together
7. **Commons Lang 3, iText to OpenPDF, Commons IO, Guava, POI, OpenCSV** (Axes 6-10, 14) --
   optional for Java 21, independent of each other

After each axis, run `mvn -B clean test` and compare against the baseline above
(50 tests, 0 failures, 1 skipped).
