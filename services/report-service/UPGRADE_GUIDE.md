# Report Service Dependency Upgrade Guide

This document describes 11 upgrade axes for migrating the report-service from its
original legacy stack to a modern, supported baseline. Each axis lists the exact
files, imports, and annotations that change, together with a verification step.

Axes 1-5, 7 and 11 (the Java 17 / Spring Boot 3.2 cutover) are **done**; the
remaining library bumps are independent follow-ups that the service does not need
in order to build and run on 17.

---

## Overview

| # | Axis | From | To | Files Affected | Status |
|---|------|------|----|----------------|--------|
| 1 | Java version | 1.8 | 17 | `pom.xml` | done |
| 2 | Spring Boot | 2.5.14 | 3.2+ | `pom.xml` | done (3.2.12) |
| 3 | javax to jakarta | `javax.*` | `jakarta.*` | All Java source files | done |
| 4 | JUnit 4 to JUnit 5 | JUnit 4 | JUnit 5 / Jupiter | All test files | done |
| 5 | SpringFox to springdoc | SpringFox 3.0.0 | springdoc-openapi 2.x | `SwaggerConfig.java`, `ReportController.java`, model classes | done (2.5.0) |
| 6 | iText 5 to OpenPDF / iText 7 | iText 5.5.13.3 | OpenPDF 1.3+ or iText 7+ | `PdfReportGenerator.java` | todo |
| 7 | Commons Lang 2 to 3 | `commons-lang:commons-lang:2.6` | `org.apache.commons:commons-lang3:3.14+` | `ReportDateUtils.java`, `PdfReportGenerator.java`, `ExcelReportGenerator.java`, `ReportDataFetcher.java` | done (BOM-managed) |
| 8 | Commons IO | 2.6 | 2.15+ | `pom.xml`, `ReportController.java` | todo |
| 9 | Guava | 28.0-jre | 33+ | `pom.xml`, `ReportDataFetcher.java` | todo |
| 10 | Apache POI | 4.1.2 | 5.2+ | `pom.xml`, `ExcelReportGenerator.java` | todo |
| 11 | Mockito | 3.12.4 | 5.x | `pom.xml`, all test files | done (BOM-managed) |

---

## Axis 1 -- Java Version (1.8 to 17)

### What changes

**File:** `pom.xml`

```xml
<!-- BEFORE -->
<java.version>1.8</java.version>
<maven.compiler.source>1.8</maven.compiler.source>
<maven.compiler.target>1.8</maven.compiler.target>

<!-- AFTER -->
<java.version>17</java.version>
<maven.compiler.source>17</maven.compiler.source>
<maven.compiler.target>17</maven.compiler.target>
```

Also update the `maven-compiler-plugin` configuration block:

```xml
<!-- BEFORE -->
<source>1.8</source>
<target>1.8</target>

<!-- AFTER -->
<source>17</source>
<target>17</target>
```

### How to verify

```bash
mvn compile
java -version   # must report 17+
```

All source files must compile without errors under Java 17.

---

## Axis 2 -- Spring Boot (2.5.14 to 3.2+)

### What changes

**File:** `pom.xml`

```xml
<!-- BEFORE -->
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>2.5.14</version>
</parent>

<!-- AFTER -->
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.5</version>
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
# No javax imports should remain (except javax.sql which is still valid in Java 17)
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
    <version>3.2.5</version>
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

<!-- ADD -->
<dependency>
    <groupId>org.springdoc</groupId>
    <artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>
    <version>2.3.0</version>
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
    <version>1.3.35</version>
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

**Option B -- iText 7 (commercial license):**

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
    <version>3.14.0</version>
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

## Axis 8 -- Commons IO (2.6 to 2.15+)

### What changes

**Files affected:** `pom.xml`, `controller/ReportController.java`

In `pom.xml`:

```xml
<!-- BEFORE -->
<commons-io.version>2.6</commons-io.version>

<!-- AFTER -->
<commons-io.version>2.15.1</commons-io.version>
```

No import changes needed. `org.apache.commons.io.FileUtils.readFileToByteArray` has
the same signature in 2.15. The upgrade addresses known CVEs in 2.6.

### How to verify

```bash
mvn dependency:tree | grep commons-io
# Should show commons-io:commons-io:jar:2.15.1
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

## Axis 10 -- Apache POI (4.1.2 to 5.2+)

### What changes

**Files affected:** `pom.xml`, `service/ExcelReportGenerator.java`

In `pom.xml`:

```xml
<!-- BEFORE -->
<poi.version>4.1.2</poi.version>

<!-- AFTER -->
<poi.version>5.2.5</poi.version>
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
# Should show org.apache.poi:poi:jar:5.2.5 and poi-ooxml:5.2.5
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

Mockito 5.x requires Java 11+. Since Axis 1 upgrades to Java 17, this is satisfied.

Key changes in Mockito 5:

- Inline mock maker is the default (no more `mockito-inline` artifact needed).
- `@RunWith(MockitoJUnitRunner.class)` becomes `@ExtendWith(MockitoExtension.class)`.
- Stricter stubbing by default (unnecessary stubs cause test failure).

### How to verify

```bash
mvn test   # all tests pass with Mockito 5
```

---

## Recommended Upgrade Order

1. **Java 17** (Axis 1) -- prerequisite for everything else
2. **javax to jakarta** (Axis 3) -- prerequisite for Spring Boot 3
3. **Spring Boot 3.2** (Axis 2) -- includes Security, Web, Data JPA changes
4. **SpringFox to springdoc** (Axis 5) -- removes the ant-path-matcher workaround
5. **JUnit 4 to JUnit 5** (Axis 4) -- can be done in parallel with Spring Boot upgrade
6. **Mockito 5** (Axis 11) -- pairs with JUnit 5
7. **Commons Lang 3** (Axis 7) -- simple package rename
8. **iText 5 to OpenPDF** (Axis 6) -- simple package rename if using OpenPDF
9. **Commons IO** (Axis 8) -- version bump only
10. **Guava 33** (Axis 9) -- version bump only (or migrate to Caffeine)
11. **Apache POI 5** (Axis 10) -- version bump only

After each axis, run `mvn clean test` to confirm nothing is broken before
proceeding to the next.
