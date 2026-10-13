# report-service-modern

Java 21 / Spring Boot 3 port of [`services/report-service`](../report-service) (the frozen Java 8 baseline).
Both modules live side by side: the legacy module stays untouched as the "before" state, this one is the "after".
The REST contract (paths, payloads, status codes, JSON timestamp format) is the same as legacy, and a golden
contract test enforces it.

## Before / after

| Axis | Legacy `report-service` | `report-service-modern` |
|---|---|---|
| JDK | 8 (Temurin 8 JRE) | **21** LTS (Temurin 21 JRE) |
| Spring Boot | 2.5.15 | 3.3.5 (Spring 6.1, Hibernate 6.5) |
| Namespaces | `javax.persistence/validation/servlet/transaction` | `jakarta.*` (incl. `jakarta.transaction.Transactional`) |
| HTTP client | `RestTemplate` + Apache HttpClient 4.5 | `RestClient` on the JDK `HttpClient` |
| Cache | Guava 28 `LoadingCache` | Caffeine (Boot managed) |
| Dates | `java.util.Date`, `SimpleDateFormat`, `Calendar` | `java.time.Instant` / `DateTimeFormatter` (UTC) |
| Commons Lang | 2.6 | commons-lang3 (Boot managed) |
| Commons IO | 2.6 | 2.17.0 |
| Commons Text | 1.9 (CVE-2022-42889) | 1.12.0 |
| OpenCSV | 4.6 | 5.9 (explicit UTF-8 writer) |
| PDF | iText 5.5.13 (AGPL) | OpenPDF 1.4.2 (LGPL/MPL, `com.lowagie` API) |
| Excel | Apache POI 4.1.2 | Apache POI 5.3.0 |
| API docs | SpringFox 3 (Swagger 2, `/v2/api-docs`) | springdoc 2.6 (OpenAPI 3, `/v3/api-docs`, `/swagger-ui.html`) |
| Security | `WebSecurityConfigurerAdapter`, `antMatchers` | `SecurityFilterChain` bean, `requestMatchers` |
| Config | `@Value` fields | `@ConfigurationProperties` record (`ReportProperties`) |
| DTOs | mutable POJOs | Java records (`ReportRequest`, `ReportResponse`) |
| Async | default `@Async` pool | `@Async` on virtual threads (`spring.threads.virtual.enabled`) |
| Tests | JUnit 4, Mockito 3.12 | JUnit 5, Mockito 5, plus golden contract test |
| Image | single JRE 8 layer, `useradd appuser` | layered Boot jar, JRE 21, UID 1001 |

**Why JDK 21 over 17:** both are LTS and Spring Boot 3.3 supports both. 21 gets free updates for longer,
supports virtual threads (used for request handling and `@Async` generation, which is blocking I/O to three
upstream services), and lets the code use records with pattern matching and switch expressions. The code
needs nothing newer than 17 except virtual threads, so moving back to 17 means changing `java.version` and
dropping `spring.threads.virtual.enabled`.

## Contract parity

* `contract/scenarios.json` has 31 requests: health, create with ISO, epoch-millis and date-only dates,
  terminal status polling, PDF/CSV/XLSX downloads, list filters, validation errors (400), malformed JSON,
  415, 404/405 cases, delete and re-delete.
* `contract/legacy-golden.json` is the normalized transcript recorded from the **legacy** container.
* `ContractParityTest` (runs in `mvn verify`) replays the scenarios against this service on a random port and
  fails on any difference from the legacy golden.
* `contract/parity.py compare --legacy URL --modern URL` runs the same scenarios against two live services and
  diffs them.

```bash
# run both next to each other (legacy :8091, modern :8092)
docker compose -f docker-compose.infra.yml -f docker-compose.yml -f docker-compose.report-modern.yml \
  --profile report-modern up -d postgres report-service report-service-modern
python3 services/report-service-modern/contract/parity.py compare \
  --legacy http://localhost:8091 --modern http://localhost:8092 \
  --golden services/report-service-modern/contract/legacy-golden.json
```

### Deliberate, documented differences

* **API docs path:** `/v3/api-docs` and `/swagger-ui.html` replace SpringFox's `/v2/api-docs`. These endpoints
  are tooling, not part of the reports API.
* **CSV encoding:** always UTF-8. Legacy used the platform default charset.
* **Schema selection:** `DB_SCHEMA` (default `public`, same as legacy) lets the modern service share the
  database without sharing the table. `error_message` is a plain `text` column; legacy's `@Lob` mapping is not used.

## Build / run

```bash
cd services/report-service-modern
mvn verify                      # JDK 21: unit + integration + golden contract tests
docker build -t report-service-modern .
# behind a Maven mirror: docker build --secret id=maven_settings,src=$HOME/.m2/settings.xml ...
```
