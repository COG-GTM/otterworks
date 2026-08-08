# Report Service Dependency Upgrade — Status

The Java 8 / Spring Boot 2.5 modernization described by the original 11-axis plan has
landed. This file records what changed and what is still outstanding.

## Completed

| # | Axis | From | To |
|---|------|------|----|
| 1 | Java version | 1.8 | 17 (`<java.version>`, compiler `<release>`) |
| 2 | Spring Boot | 2.5.14 | 3.2.x (`spring-boot-starter-parent`) |
| 3 | javax → jakarta | `javax.persistence/validation/transaction` | `jakarta.*` |
| 4 | JUnit 4 → 5 | `junit:junit`, `@RunWith(SpringRunner.class)` | Jupiter via `spring-boot-starter-test` |
| 5 | SpringFox → springdoc | `springfox-boot-starter` 3.0.0 | `springdoc-openapi-starter-webmvc-ui` 2.5.0 |
| 7 | Commons Lang | `commons-lang:commons-lang:2.6` | `commons-lang3` (Boot-managed) |
| 8 | Commons IO | 2.6 | 2.15.1 |
| 9 | Guava | 28.0-jre | 33.1.0-jre |
| 10 | Apache POI | 4.1.2 | 5.2.5 |
| 11 | Mockito | 3.12.4 | Boot-managed 5.x + `mockito-junit-jupiter` |

Related Spring Boot 3 / Spring 6 changes that came with axis 2:

- `SecurityConfig` no longer extends `WebSecurityConfigurerAdapter`; it exposes a
  `SecurityFilterChain` bean using the lambda DSL, `authorizeHttpRequests`, and
  `requestMatchers`. `XXssConfig.block(boolean)` was removed in Security 6, so the
  X-XSS-Protection header is set via `headerValue(ENABLED_MODE_BLOCK)`.
- Apache HttpClient 4 → 5 (`org.apache.hc.client5`). `HttpComponentsClientHttpRequestFactory
  .setReadTimeout(int)` was removed in Spring 6, so the socket timeout is configured on the
  pooling connection manager via `ConnectionConfig`.
- `spring.mvc.pathmatch.matching-strategy=ant-path-matcher` (a SpringFox workaround) and the
  explicit `hibernate.dialect` properties are gone — Boot 3 and Hibernate 6 handle both.
- CI (`ci.yml`, `docker-build.yml`) and the Dockerfile build/runtime images are on Temurin 17.

## Outstanding follow-ups

- **Axis 6 — iText 5 → OpenPDF.** `com.itextpdf:itextpdf:5.5.13.3` is AGPL and unmaintained.
  OpenPDF (`com.github.librepdf:openpdf`) is an API-compatible LGPL fork; the change is a
  package rename from `com.itextpdf.text.*` to `com.lowagie.text.*` in `PdfReportGenerator`.
  Deferred to keep the runtime migration reviewable.
- **Trivy exclusion.** `security-scan.yml` still passes `--skip-dirs services/report-service`,
  added when the service was intentionally outdated. It can now be dropped.
- **Optional modernization** deliberately not attempted here: `java.util.Date` →
  `java.time.Instant`, POJOs → records, `RestTemplate` → `RestClient`, Guava cache → Caffeine.

## How to verify

```bash
cd services/report-service
mvn -B verify                                  # compiles and tests on JDK 17
grep -rn "import javax\." src/                 # returns nothing
curl http://localhost:8091/v3/api-docs         # OpenAPI 3 JSON
open http://localhost:8091/swagger-ui.html     # redirects to /swagger-ui/index.html
```
