# legacy-portal decomposition inventory

Baseline inventory for splitting `services/legacy-portal` (one Spring Boot 2.7 / Java 11 JVM,
three bounded contexts) into **announcements-service**, **preferences-service** and
**feedback-service** on Spring Boot 3 / JDK 17.

Decisions fixed for the whole migration (not revisited per step):

| Topic | Decision |
|---|---|
| Target runtime | JDK **17**, Spring Boot **3.x** |
| Data ownership | **schema-per-service with its own credentials** on the tenant's single Postgres database |
| Routing | **no api-gateway routes** — each service is reached on its own port, as legacy-portal is today |
| Helm verification | install on a **local kind cluster** only |
| Delivery | stacked commits on `devin/legacy-portal-decomposition`, one PR at the end, nothing merged, nothing deployed |

Everything below was measured on this branch's base commit (`main` @ `cc23bf19`) unless marked
otherwise. Response bodies are real `curl` output from the fat JAR (`java -jar target/legacy-portal.jar`,
JDK 11); DDL is Hibernate's own `org.hibernate.SQL` log for `ddl-auto: update` against an empty
H2 in-memory database and an empty `postgres:15-alpine` initialised with `scripts/initdb.sql`.

## 1. The monolith as built today

| Fact | Value | Source |
|---|---|---|
| Build | Maven, wrapper pins Maven 3.9.9 | `.mvn/wrapper/maven-wrapper.properties` |
| Parent | `spring-boot-starter-parent` **2.7.18** | `pom.xml` |
| Java | 11 (`java.version`, `maven.compiler.source/target`) | `pom.xml` |
| ORM | Hibernate ORM **5.6.15.Final**, `javax.persistence` | startup log |
| Starters | web, data-jpa, validation (`javax.validation`), actuator | `pom.xml` |
| Extra deps | `commons-configuration2` 2.8.0 (pulls `commons-text` **1.9** transitively), `commons-beanutils` 1.11.0 | `pom.xml` |
| Runtime DBs | H2 (default profile, tests, `run-onprem.sh`), PostgreSQL (`postgres` profile) | `application.yml` |
| Port | **8095** (`server.port`) | `application.yml` |
| Artifact | `target/legacy-portal.jar` (`finalName`) | `pom.xml` |
| Actuator | `health,info` exposed; health probes enabled (`/actuator/health/liveness`, `/readiness`) | `application.yml` |
| Packages | `com.otterworks.legacyportal.{announcements,userpreferences,feedback,common}` + `LegacyPortalApplication` | `src/main/java` |

`javax.*` usages that the Boot 3 step must move to `jakarta.*`: `javax.persistence.*` (3 entities),
`javax.validation.*` (3 controllers), `javax.annotation.PostConstruct` (`PortalBrandingSettings`).

### Route index (every HTTP route the JVM serves)

| Method | Path | Owner | Section |
|---|---|---|---|
| GET | `/health` | common (`HealthController`) | §7 |
| GET | `/actuator/health` (+ `/liveness`, `/readiness`) → `{"status":"UP","groups":["liveness","readiness"]}` | Spring Boot Actuator | §1 |
| GET | `/actuator/info` → `{}` | Spring Boot Actuator | §1 |
| GET | `/api/announcements?publishedOnly=` | announcements | §3 |
| GET | `/api/announcements/{id}` | announcements | §3 |
| POST | `/api/announcements` | announcements | §3 |
| POST | `/api/announcements/{id}/publish` | announcements | §3 |
| GET | `/api/preferences/{userId}` | userpreferences | §4 |
| PUT | `/api/preferences/{userId}` | userpreferences | §4 |
| POST | `/api/feedback` | feedback | §5 |
| GET | `/api/feedback?userId=` | feedback | §5 |
| GET | `/api/feedback/average-rating` | feedback | §5 |

Checked with `rg -n '@(Get|Post|Put|Delete|Patch|Request)Mapping' src/main/java`.

## 2. Shared error mapping (`common/GlobalExceptionHandler`)

`@ControllerAdvice` applied to every controller in the JVM:

| Exception (or cause) | Status | Body |
|---|---|---|
| `java.util.NoSuchElementException` | 404 | `{"error":"Not Found","message":"<ex.getMessage()>"}` |
| `java.lang.IllegalArgumentException` (incl. subclasses such as `NumberFormatException`, and as a *cause* — Spring 5.3 matches causes) | 400 | `{"error":"Bad Request","message":"<ex.getMessage()>"}` |

Everything else falls through to Spring Boot's `BasicErrorController`, whose body has **no
`message`** (`server.error.include-message` defaults to `never`) and **no `errors` list**:

```json
{"timestamp":"2026-09-29T18:49:35.662+00:00","status":400,"error":"Bad Request","path":"/api/announcements"}
```

That default body is what clients get for: `@Valid` failures (`MethodArgumentNotValidException`),
malformed JSON (`HttpMessageNotReadableException`), a missing required `@RequestParam`
(`MissingServletRequestParameterException`), 405 on an unmapped method, and 404 on an unknown path.
Parity tests must compare `status`, `error`, `path` and ignore `timestamp`.

## 3. Bounded context: announcements

Package `com.otterworks.legacyportal.announcements` — `Announcement`, `AnnouncementController`,
`AnnouncementRepository`, `AnnouncementService`.

### Routes

| Method & path | Request | Success | Errors |
|---|---|---|---|
| `GET /api/announcements?publishedOnly={bool}` | `publishedOnly` optional, default `true` | 200, `AnnouncementResponse[]` | non-boolean `publishedOnly` → 400 `{"error":"Bad Request","message":"Invalid boolean value [maybe]"}` (IllegalArgumentException cause → handler) |
| `GET /api/announcements/{id}` | `id` Long | 200, `AnnouncementResponse` | unknown id → 404 `{"error":"Not Found","message":"announcement 999 not found"}`; non-numeric id → 400 `{"error":"Bad Request","message":"For input string: \"abc\""}` (NumberFormatException cause → handler) |
| `POST /api/announcements` | `CreateAnnouncementRequest` JSON | **201**, `AnnouncementResponse` | validation / malformed JSON → 400 default body |
| `POST /api/announcements/{id}/publish` | no body | 200, `AnnouncementResponse` (`published:true`) | unknown id → 404 as above; non-numeric id → 400 as above |

`CreateAnnouncementRequest`: `title` `@NotBlank @Size(max=200)`, `body` `@NotBlank @Size(max=4000)`,
`published` primitive `boolean` (absent → `false`).

`AnnouncementResponse`: `{"id":1,"title":"Release","body":"v1 is out","published":false,"createdAt":"2026-09-29T18:49:35.488064Z"}`
(`createdAt` is an ISO-8601 `Instant` string).

Behaviour: `publishedOnly=true` → `findByPublishedTrueOrderByCreatedAtDesc` (newest first);
`publishedOnly=false` → `findAll()` (no `ORDER BY`, order is database-defined). `publish` is
idempotent (re-publishing returns 200). `createdAt` is set in the constructor and is `updatable=false`.

### Entity, schema, DDL

`@Entity @Table(name="announcement", schema="announcements")` — `id Long` (`IDENTITY`),
`title` (200, not null), `body` (4000, not null), `published` (not null), `createdAt Instant` (not null, not updatable).

| DB | DDL produced by `ddl-auto: update` |
|---|---|
| H2 (`H2Dialect`) | `create table announcements.announcement (id bigint generated by default as identity, body varchar(4000) not null, created_at timestamp not null, published boolean not null, title varchar(200) not null, primary key (id))` |
| PostgreSQL 15 (`PostgreSQLDialect`) | `create table announcements.announcement (id  bigserial not null, body varchar(4000) not null, created_at timestamp not null, published boolean not null, title varchar(200) not null, primary key (id))` → implicit sequence `announcements.announcement_id_seq` |

### Uses from `common`

No compile-time import. At runtime it relies on `GlobalExceptionHandler` for its 404
(`NoSuchElementException` from `AnnouncementService.get`) and for the 400 (with `message`) on a non-numeric `{id}` or non-boolean `publishedOnly`.
The extracted service must carry both mappings.

## 4. Bounded context: userpreferences

Package `com.otterworks.legacyportal.userpreferences` — `UserPreference`, `UserPreferenceController`,
`UserPreferenceRepository`, `UserPreferenceService`.

### Routes

| Method & path | Request | Success | Errors |
|---|---|---|---|
| `GET /api/preferences/{userId}` | `userId` String (no length check on the path) | 200, `PreferenceResponse`; unknown user → **defaults, not persisted**: `{"userId":"u1","theme":"light","locale":"en-US","emailNotifications":true}` | — |
| `PUT /api/preferences/{userId}` | `UpdatePreferenceRequest` JSON | 200, `PreferenceResponse` (upsert: creates or updates) | validation / malformed JSON → 400 default body |

`UpdatePreferenceRequest`: `theme` `@NotBlank @Size(max=20)`, `locale` `@NotBlank @Size(max=20)`,
`emailNotifications` primitive `boolean` (absent → `false`).

`PreferenceResponse`: `{"userId":"u1","theme":"dark","locale":"nl-NL","emailNotifications":false}`.

Defaults (`UserPreferenceService`): `DEFAULT_THEME="light"`, `DEFAULT_LOCALE="en-US"`, `emailNotifications=true`.
A `userId` longer than 100 characters on `PUT` would reach the database and fail on the column
length (not reachable through validation; not exercised by the current tests).

### Entity, schema, DDL

`@Entity @Table(name="user_preference", schema="user_preferences")` — `userId` String PK
(`user_id`, 100), `theme` (20, not null), `locale` (20, not null), `emailNotifications`
(`email_notifications`, not null). No generated id.

| DB | DDL produced by `ddl-auto: update` |
|---|---|
| H2 | `create table user_preferences.user_preference (user_id varchar(100) not null, email_notifications boolean not null, locale varchar(20) not null, theme varchar(20) not null, primary key (user_id))` |
| PostgreSQL 15 | `create table user_preferences.user_preference (user_id varchar(100) not null, email_notifications boolean not null, locale varchar(20) not null, theme varchar(20) not null, primary key (user_id))` |

### Uses from `common`

Nothing in practice: no compile-time import, and neither `NoSuchElementException` nor
`IllegalArgumentException` is thrown on its paths (`userId` is a String, so no conversion
failure). All its errors come from Boot's default error body.

## 5. Bounded context: feedback

Package `com.otterworks.legacyportal.feedback` — `Feedback`, `FeedbackController`,
`FeedbackRepository`, `FeedbackService`.

### Routes

| Method & path | Request | Success | Errors |
|---|---|---|---|
| `POST /api/feedback` | `SubmitFeedbackRequest` JSON | **201**, `FeedbackResponse` | validation (incl. rating outside 1..5) / malformed JSON → 400 default body |
| `GET /api/feedback?userId={id}` | `userId` **required** | 200, `FeedbackResponse[]`, newest first | missing `userId` → 400 default body |
| `GET /api/feedback/average-rating` | — | 200, `{"averageRating":4.0}`; empty table → `{"averageRating":0.0}` | — |

`SubmitFeedbackRequest`: `userId` `@NotBlank @Size(max=100)`, `rating` primitive `int` `@Min(1) @Max(5)`
(absent → `0` → 400), `message` `@NotBlank @Size(max=2000)`.

`FeedbackResponse`: `{"id":1,"userId":"u1","rating":4,"message":"good","createdAt":"2026-09-29T18:49:35.750306Z"}`.

`FeedbackService.submit` also throws `IllegalArgumentException("rating must be between 1 and 5")`,
which `GlobalExceptionHandler` would map to 400 with a `message`. Over HTTP it is **unreachable**
(bean validation rejects first and returns the default body); it is only observable by calling
the service directly (`FeedbackServiceTest.rejectsOutOfRangeRating`). `averageRating` loads all
rows (`findAll()`) and averages in memory.

### Entity, schema, DDL

`@Entity @Table(name="feedback", schema="feedback")` — `id Long` (`IDENTITY`), `userId`
(`user_id`, 100, not null), `rating int` (not null), `message` (2000, not null),
`createdAt Instant` (not null, not updatable).

| DB | DDL produced by `ddl-auto: update` |
|---|---|
| H2 | `create table feedback.feedback (id bigint generated by default as identity, created_at timestamp not null, message varchar(2000) not null, rating integer not null, user_id varchar(100) not null, primary key (id))` |
| PostgreSQL 15 | `create table feedback.feedback (id  bigserial not null, created_at timestamp not null, message varchar(2000) not null, rating int4 not null, user_id varchar(100) not null, primary key (id))` → implicit sequence `feedback.feedback_id_seq` |

### Uses from `common`

No compile-time import. `GlobalExceptionHandler` only matters for the service-level
`IllegalArgumentException`, which HTTP clients cannot trigger today.

## 6. Schemas and database setup

- **H2** (default profile): the JDBC URL itself creates all three schemas —
  `jdbc:h2:mem:legacyportal;DB_CLOSE_DELAY=-1;DB_CLOSE_ON_EXIT=FALSE;INIT=CREATE SCHEMA IF NOT EXISTS ANNOUNCEMENTS\;CREATE SCHEMA IF NOT EXISTS USER_PREFERENCES\;CREATE SCHEMA IF NOT EXISTS FEEDBACK`.
  `DB_CLOSE_DELAY=-1` keeps the named in-memory DB alive for the whole JVM, so every Spring
  context in a test run shares the same data (see §10).
- **PostgreSQL** (`postgres` profile): `scripts/initdb.sql` runs `CREATE SCHEMA IF NOT EXISTS`
  for `announcements`, `user_preferences`, `feedback`; all three are owned by the single
  `legacyportal` role. Datasource from `SPRING_DATASOURCE_URL/USERNAME/PASSWORD`
  (defaults `jdbc:postgresql://localhost:5432/legacyportal`, `legacyportal`/`legacyportal`).
  Measured catalog after startup: exactly the three tables above; `id` columns default to
  `nextval('<schema>.<table>_id_seq')`; `created_at` is `timestamp without time zone`.
- There are **no** foreign keys, views, cross-schema joins or native queries; every query is
  a Spring Data derived query or `findAll/findById/save`.

Hibernate 6 (Boot 3 step) changes the generated PostgreSQL DDL for ids and would change it for
`Instant`; what was measured and pinned is in §12. The target "own credentials per schema" model
replaces the single `legacyportal` owner.

## 7. `common` package → `services/portal-common`

Moved out of the monolith into the Boot 3 library `services/portal-common` (package
`com.otterworks.portal.common`), a module of the `services/portal-parent` reactor. Every portal
service gets it by depending on `com.otterworks:portal-common`; nothing is copied.
`PortalCommonAutoConfiguration` (registered in
`META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`, servlet
applications only, each bean `@ConditionalOnMissingBean`) and `PortalCommonEnvironmentPostProcessor`
provide:

| Class | What it does | Used by |
|---|---|---|
| `HealthController` | `GET /health` → `{"status":"UP","service":"<service>","banner":"OtterWorks Portal (on-prem) - contact portal-support@otterworks.example"}`. `service` is `portal.common.service-name`, defaulting to `spring.application.name` (`legacy-portal` for the monolith). | ops / healthchecks (Dockerfile, `docker-compose.onprem.yml`), `LegacyPortalApplicationTest`, `HealthControllerTest`. Depends on `PortalBrandingSettings`. |
| `GlobalExceptionHandler` | error mapping, §2 | announcements (404, 400 on bad `{id}` / `publishedOnly`); feedback (service-level only); userpreferences (none); `GlobalExceptionHandlerTest` |
| `PortalBrandingSettings` | `@PostConstruct` loads `portal-settings.properties` (shipped in the library jar) from the classpath via commons-configuration2 `FileBasedConfigurationBuilder<PropertiesConfiguration>`; `bannerText()`, `supportContact()`, `interpolate(template)` | `HealthController`; `PortalBrandingSettingsTest`; legacy-portal `deps/DependencyTranscriptEmitterTest` (dependency harness) |
| `LegacyWebMvcConfig` | trailing-slash match, §12 | every route |
| `PortalCommonEnvironmentPostProcessor` | lowest-precedence defaults `server.error.include-*` and `spring.mvc.problemdetails.enabled: false`, §12 (a service's own configuration still wins) | every service's default error body |

No domain code lives in the library. Its own tests (`services/portal-common/src/test`) cover the
error mapping, the health payload, the auto-configuration conditions, the pinned defaults and a
sample service booted with only the library (`app/PortalCommonServiceTest`).

`portal-settings.properties`:

```properties
portal.environment=on-prem
portal.support=portal-support@otterworks.example
portal.banner=OtterWorks Portal (${portal.environment}) - contact ${portal.support}
portal.classification=${base64Decoder:SU5URVJOQUw=}
```

The interpolation behaviour of this file is under contract in `security/deps` (§9): the
banner/support values, `base64Decoder`, `sys:`, `file:` resolve; `script:` and `url:` must stay
unresolved. `portal-common` carries `PortalBrandingSettings` and inherits that contract; the
transcript is still recorded through legacy-portal (`cases/legacy-portal.json`), and
`portal-common` is registered in `security/deps/modules.yaml` for its tree and suite.

## 8. Proof: no cross-context imports or calls

Run from `services/legacy-portal/src/main/java/com/otterworks/legacyportal`:

```text
$ rg -n 'legacyportal\.(userpreferences|feedback)' announcements
(no matches)
$ rg -n 'legacyportal\.(announcements|feedback)' userpreferences
(no matches)
$ rg -n 'legacyportal\.(announcements|userpreferences)' feedback
(no matches)
$ rg -n 'legacyportal\.(announcements|userpreferences|feedback)' common
(no matches)
$ rg -n 'legacyportal\.common' announcements userpreferences feedback
(no matches)
$ rg -n -w 'UserPreference\w*|Feedback\w*' announcements
(no matches)
$ rg -n -w 'Announcement\w*|Feedback\w*' userpreferences
(no matches)
$ rg -n -w 'Announcement\w*|UserPreference\w*' feedback
(no matches)
$ rg -n 'RestTemplate|WebClient|HttpClient|FeignClient|URLConnection' .
(no matches)
$ rg -n 'ApplicationEvent|EventListener|ApplicationEventPublisher' .
(no matches)
```

The README's claim holds: the contexts share only the JVM, the single datasource / persistence
unit (component scan from `LegacyPortalApplication`), port 8095 and the `common` beans wired at
runtime. The only test that touches more than one context is `LegacyPortalApplicationTest`.

## 9. Everything outside the module that references legacy-portal

Found with `rg -n -i 'legacy-portal|legacy_portal|legacyportal' --hidden -g '!services/legacy-portal/**' -g '!.git/**'`
(and `rg -n 8095` outside the module: only unrelated substrings in CSV/lock files). Nothing in `docker-compose*.yml` at the repo root,
`infrastructure/helm/**`, `services/api-gateway/**`, `docs/api-route-matrix.md`, `scripts/**`,
the `Makefile` or `cd-tenant.yml` references it — legacy-portal is not part of any tenant deploy today.

| File | Lines | What it does | Impact on the split |
|---|---|---|---|
| `.github/workflows/ci.yml` | 32, 71-72 (paths filter `services/legacy-portal/**`), 337-353 (job `legacy-portal`: temurin **11**, `./mvnw test -B`) | CI on push to `main` / PRs to `main` only | Needs a filter + job per new service on JDK 17. |
| `.github/workflows/docker-build.yml` | 60-70 (`legacy-portal-tests`: JDK 11, `./mvnw test -B`), 74 (`build-and-push.needs`) | Release gate; legacy-portal is tested but **not** in the image matrix | Swap the gate for the three services; decide whether they join the matrix (no release is cut in this migration). |
| `.github/workflows/deps-remediation.yml` | 8, 16 (path triggers), 29-37 (JDK 17 + 11) | Runs `make deps-inventory / deps-tests / deps gate / transcript` on **any branch push** touching `services/legacy-portal/**` | Fires on pushes to this branch. Its `deps-tests` step runs `./mvnw -B test` here, so it had the same test-order failure as §10. |
| `security/deps/modules.yaml` | 32-45 | Registers module `legacy-portal` (`java_home` JDK 17 since the Java 17 step, with standalone Nashorn on the test classpath for the transcript — §12; `tool: ./mvnw, mvn`, `test: -B test`, `cases: cases/legacy-portal.json`). Discovery **fails the gate for any unregistered JVM build file** | Every new `pom.xml` must be registered (or exempted) in the same commit that adds it, on JDK 17 with the same Nashorn arrangement. |
| `security/deps/cases/legacy-portal.json` | whole file | 7 contract cases against `PortalBrandingSettings` (banner, support, base64, sys, file, script-unresolved, url-unresolved) | Follows whichever module owns `PortalBrandingSettings` after the split. |
| `security/deps/expected/legacy-portal.json` | whole file | Recorded baseline transcript (commons-text 1.9), `cases_sha256` pinned | Moves/re-records with the cases; `script:` case behaviour is JDK-dependent. |
| `.devin/blueprint.yaml` | 27-29 (comment claims legacy-portal is "Boot 3.2" and installs JDK 17 only), 166 (`./mvnw -B -q dependency:go-offline` warm-up) | Session VM setup | Comment is inaccurate today (pom is Boot 2.7.18 / Java 11); warm-up needs the new modules. |
| `.gitignore` | 27 (`services/legacy-portal/target/`) | Ignore build output | Add `target/` for new modules. |
| `.agents/skills/dependency-cve-remediation/SKILL.md` | 38, 55, 75, 89, 108-110, 137, 149, 166, 184 | Agent skill describing legacy-portal as the transitive commons-text consumer | Doc update once `PortalBrandingSettings` moves. |
| `.workshop/playbooks/dependency-cve-remediation.devin.md` | 169 | Playbook sample gate output naming legacy-portal | Doc only. |

In-module deploy/run artifacts that model the "runs on a VM today" path (all assume one JAR on 8095):

| File | Role |
|---|---|
| `Dockerfile` | `maven:3.9-eclipse-temurin-11` build → `eclipse-temurin:11-jre-jammy`, uid 1001, `EXPOSE 8095`, `HEALTHCHECK curl /health` |
| `docker-compose.onprem.yml` | `legacy-portal-db` (postgres:15-alpine, `initdb.sql`, volume `legacy-portal-db-data`) + `legacy-portal` (`SPRING_PROFILES_ACTIVE=postgres`, port 8095, healthcheck `/health`) |
| `deploy/legacy-portal.service` | systemd unit: user `legacyportal`, `/opt/legacy-portal/legacy-portal.jar`, `EnvironmentFile=-/etc/legacy-portal.env` |
| `scripts/run-onprem.sh` | builds with `./mvnw -DskipTests package` and runs the fat JAR (H2 default) |
| `scripts/initdb.sql` | creates the three schemas |

## 10. Test suite and baseline status

| Test | Scope | Context(s) |
|---|---|---|
| `LegacyPortalApplicationTest` | `@SpringBootTest` + MockMvc: `/health`, `/actuator/health`, announcements round trip, preferences defaults, feedback rating 400 | all + common |
| `announcements/AnnouncementServiceTest` | `@DataJpaTest` (real H2 URL, `Replace.NONE`) | announcements |
| `userpreferences/UserPreferenceServiceTest` | `@DataJpaTest` | userpreferences |
| `feedback/FeedbackServiceTest` | `@DataJpaTest` | feedback |
| portal-common `PortalBrandingSettingsTest`, `GlobalExceptionHandlerTest`, `HealthControllerTest`, `PortalCommonAutoConfigurationTest`, `PortalCommonEnvironmentPostProcessorTest`, `app/PortalCommonServiceTest` | library suite (§7), run by the reactor | common |
| `deps/DependencyTranscriptEmitterTest` | skipped unless the `security/deps` harness passes `-Dow.deps.*` | common |

`./mvnw verify` on JDK 11 at `main` @ `cc23bf19` was **red** (16 run, 1 failure, 1 skipped):
`AnnouncementServiceTest.listPublishedReturnsOnlyPublishedNewestFirst` saw an extra `"Release"`
row committed by `LegacyPortalApplicationTest` (surefire runs it first; the named H2 in-memory DB
survives across contexts because of `DB_CLOSE_DELAY=-1`). The commit after this document makes
`LegacyPortalApplicationTest` `@Transactional` so its MockMvc writes roll back; no assertion changes.

## 11. Commit convention for every step on this branch

- One logical change per commit; never mix a refactor with a behaviour change.
- Subject: `legacy-portal(<stage>): <imperative summary>` — e.g. `legacy-portal(baseline): ...`,
  `legacy-portal(parity): ...`, `legacy-portal(boot3): ...`, `legacy-portal(common): ...`,
  `legacy-portal(announcements): ...`, `legacy-portal(preferences): ...`, `legacy-portal(feedback): ...`,
  `legacy-portal(compose): ...`, `legacy-portal(helm): ...`, `legacy-portal(tooling): ...`,
  `legacy-portal(kind): ...`, `legacy-portal(verify): ...`.
- Body says whether the change is a `feature` or a `bug` fix and why.
- Trailer `Verified-by:` names each local command that passed for that commit, one per line, e.g.
  `Verified-by: cd services/legacy-portal && ./mvnw -B verify (JDK 11)`.
- Stack on top of the branch and push after each step; never force-push other steps' commits
  (fixups only in the final verification step); never push to `main`, `workshop-*` or `demo-*`
  (`cd-tenant.yml` builds and deploys those).

## 12. Boot 3 platform step: measured deltas and pinned defaults

Step `legacy-portal(jdk17)` / `legacy-portal(boot3)`: the monolith now builds and runs on
**JDK 17** with `spring-boot-starter-parent` **3.5.16** (Spring Framework 6.2, Hibernate ORM
6.6, H2 2.3, Tomcat 10.1). The OpenRewrite recipe `org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5`
(`rewrite-spring` 6.37.1) did the parent bump and the `javax.*` → `jakarta.*` imports (§1 list);
its split of the `postgres` document out of `application.yml` was reverted. Everything else
below was hand-applied and measured. The 20 golden transcripts (sha256 `932a1671680c`) are
unchanged and pass on H2 and PostgreSQL.

### Pinned framework defaults

| Boot 3 default change | Old behaviour kept | Where |
|---|---|---|
| Spring 6 no longer matches a trailing slash (`GET /api/announcements/` → **404**, measured with the pin removed) | Trailing slash matches the mapped route (`GET /api/announcements/`, `GET /api/preferences/{userId}/` → 200) | portal-common `LegacyWebMvcConfig` (`setUseTrailingSlashMatch(true)`, deprecated in Spring 6, removed in 7); `LegacyPortalApplicationTest.trailingSlashMatchesTheMappedRoute`, `PortalCommonServiceTest` |
| Hibernate 6 maps `Instant` to `timestamp(6) with time zone` | `created_at` stays `timestamp` (without time zone) | `@JdbcTypeCode(SqlTypes.TIMESTAMP)` on `Announcement.createdAt` and `Feedback.createdAt` |
| RFC 7807 problem details available for MVC exceptions | Off: MVC exceptions still render Boot's default error body (§2) | `spring.mvc.problemdetails.enabled: false`, supplied by portal-common `PortalCommonEnvironmentPostProcessor` |
| Error attribute exposure (unchanged between 2.7 and 3.5, pinned so extracted services inherit it) | No `message`, `errors`, `exception` or `trace` in the default body | `server.error.include-message: never`, `include-binding-errors: never`, `include-stacktrace: never`, `include-exception: false`, supplied by portal-common `PortalCommonEnvironmentPostProcessor` |

### Measured, no pin needed

- **Dialects**: the explicit `H2Dialect` / `PostgreSQLDialect` properties were removed; Hibernate 6
  resolves the dialect and database version from the connection.
- **H2 2.x**: the schema-per-context URL (`INIT=CREATE SCHEMA IF NOT EXISTS ...\;...`) works unchanged
  on H2 2.3; the `@DataJpaTest` suites and the H2 parity profile pass on it.
- **ID generation**: `GenerationType.IDENTITY` is unchanged. On an empty PostgreSQL 15 Hibernate 6
  now creates `id bigint generated by default as identity` (implicit sequence still
  `<schema>.<table>_id_seq`) instead of `bigserial`; ids still start at 1 and are assigned by the
  database. Against tables created by the Boot 2.7 DDL in §3/§5 (`bigserial`, pre-existing row)
  Boot 3 starts with `ddl-auto: update` without altering anything, inserts continue the existing
  sequence (next id 2) and the pre-upgrade row reads back with the same `createdAt`.
- **Actuator**: `health,info` exposure and `probes.enabled` are unchanged; `/actuator/health`
  still reports groups `liveness`/`readiness` with `application/vnd.spring-boot.actuator.v3+json`.
- **Serialisation and error bodies**: Jackson output (`Instant` as ISO-8601 `Z`), the `@ControllerAdvice`
  bodies of §2 (including the `Invalid boolean value [maybe]` message and cause matching) and the
  101-char `userId` write → 500 are unchanged (parity).
- **Dependencies**: `commons-configuration2` 2.8.0 and `commons-beanutils` 1.11.0 stay pinned
  (Boot 3.5 manages neither); `commons-text` stays 1.9 transitively. The only change in that
  subtree is Boot-managed `commons-lang3` 3.12.0 → 3.17.0. On JDK 17 the transcript's
  script engine comes from `org.openjdk.nashorn:nashorn-core` 15.7 (test scope) instead of the JDK;
  `security/deps/modules.yaml` runs the module on JDK 17 and the recorded cases/expected
  transcript are unchanged (all 7 cases match).


## 13. Extracted-service template (set by announcements-service)

Step `legacy-portal(announcements)` extracted the first context. preferences-service and
feedback-service copy this layout; only the names, the port and the DDL change.

### Module layout

```
services/<context>-service/
├── pom.xml                      parent portal-parent (relativePath ../portal-parent/pom.xml), finalName <context>-service
├── Dockerfile                   build context services/ (the reactor)
├── Dockerfile.dockerignore      allow-list: reactor POMs, portal-common/src/main, <module>/src/main
├── .gitignore                   target/ (also listed in the root .gitignore)
├── scripts/initdb.sh            PostgreSQL init: the service's own role + schema (see "Data ownership")
└── src/
    ├── main/java/com/otterworks/<context>/        moved package, base package renamed only
    │   └── <Context>ServiceApplication.java        plain @SpringBootApplication
    ├── main/resources/application.yml
    ├── main/resources/db/migration/h2/V1__create_<table>.sql
    ├── main/resources/db/migration/postgresql/V1__create_<table>.sql
    └── test/java/com/otterworks/<context>/
        ├── <X>ServiceTest.java                     moved @DataJpaTest, package renamed only
        ├── <Context>ServiceApplicationTest.java    @SpringBootTest + MockMvc on H2, @Transactional
        └── <Context>PostgresIT.java                Testcontainers PostgreSQL, `postgres` profile
```

- Registered in the same commit as a `<module>` of `services/portal-parent/pom.xml`, in
  `security/deps/modules.yaml` (JDK 17, `tool: ../portal-parent/mvnw ... -pl :<module> -am`),
  and in the `legacy-portal` paths filter of `ci.yml` and the triggers of `deps-remediation.yml`.
- Dependencies: web, data-jpa, validation, actuator, `portal-common` (version managed by the
  parent), `flyway-core` + `flyway-database-postgresql`, H2 and PostgreSQL drivers (runtime);
  tests: `spring-boot-starter-test`, `spring-boot-testcontainers`, Testcontainers `junit-jupiter`
  and `postgresql` (all versions from the Boot BOM). `maven-failsafe-plugin` is declared so
  `*IT` classes run in `verify`.
- Nothing from portal-common is copied: `/health` (reports `spring.application.name`), the
  `GlobalExceptionHandler` mappings, branding, trailing-slash matching and the `server.error.*` /
  problem-details pins (§7, §12) arrive through its auto-configuration.

### Config keys (`application.yml`)

| Key | Default document (H2, local runs) | `postgres` profile (compose stack) |
|---|---|---|
| `server.port` | announcements **8096**, preferences 8097, feedback 8098 | same |
| `spring.application.name` | `<context>-service` | same |
| `spring.datasource.url` | `jdbc:h2:mem:<context>;DB_CLOSE_DELAY=-1;DB_CLOSE_ON_EXIT=FALSE;DATABASE_TO_LOWER=TRUE` | `${SPRING_DATASOURCE_URL:jdbc:postgresql://localhost:5432/legacyportal}` |
| `spring.datasource.username` / `password` | `sa` / empty | `${SPRING_DATASOURCE_USERNAME:<context>}` / `${SPRING_DATASOURCE_PASSWORD:<context>}` |
| `spring.flyway.schemas` / `default-schema` | `<schema>` | same |
| `spring.flyway.locations` | `classpath:db/migration/{vendor}` | same |
| `spring.flyway.create-schemas` | default (`true`: Flyway creates the H2 schema) | `false`: the schema exists and is owned by the role |
| `spring.jpa.hibernate.ddl-auto` | `validate` | same |
| `management.*` | `health,info` exposure, `probes.enabled: true` | same |

`DATABASE_TO_LOWER=TRUE` makes H2 fold unquoted identifiers to lower case as PostgreSQL does,
so Flyway's schema, the migration DDL and the entity's `schema = "<schema>"` agree without the
monolith's `INIT=CREATE SCHEMA` URL. Hibernate is never allowed to create or alter tables.

### Flyway naming

- One directory per vendor, selected by `{vendor}`: `db/migration/h2`, `db/migration/postgresql`.
- `V<n>__<verb>_<table>.sql`, lower-case snake case; V1 is `V1__create_<table>.sql`.
- V1 reproduces the DDL recorded in §3/§4/§5 **character for character** for that vendor
  (the Boot 2.7 `ddl-auto: update` output, including `bigserial` on PostgreSQL rather than the
  identity column Hibernate 6 would now generate, §12). Existing monolith databases therefore
  already match V1; a later step that attaches a service to a pre-populated schema uses
  `spring.flyway.baseline-on-migrate` rather than editing V1.
- `flyway_schema_history` lives in the service's own schema.

### Data ownership (PostgreSQL)

`scripts/initdb.sh` runs from `/docker-entrypoint-initdb.d` of the tenant database container and
creates a login role named after the context (password `<CONTEXT>_DB_PASSWORD`, local default = the
role name) plus `CREATE SCHEMA <schema> AUTHORIZATION <role>`, with `PUBLIC` revoked. The service
connects only as that role; the monolith's `scripts/initdb.sql` stops creating the schema in the
same commit. `docker-compose.onprem.yml` mounts each service's `initdb.sh` next to `initdb.sql`.

### Dockerfile

Same shape as the monolith's: `maven:3.9-eclipse-temurin-17` builder over the `services/`
context (copy reactor POMs → `dependency:go-offline -pl :<module> -am` → copy `src/main` →
`package -DskipTests`), then `eclipse-temurin:17-jre-jammy` with curl, `useradd -r -u 1001 appuser`,
`USER appuser`, `EXPOSE <port>`, `HEALTHCHECK curl -f http://localhost:<port>/health`,
`ENTRYPOINT ["java", "-jar", "app.jar"]`. Built with `docker build -f <module>/Dockerfile services/`.

### Tests

| Test | What it proves |
|---|---|
| moved `@DataJpaTest` (package rename only) | repository/service behaviour, now on the Flyway schema under `ddl-auto: validate` |
| `<Context>ServiceApplicationTest` | the context boots on H2; `/health` reports `<context>-service`; `/actuator/health`; the route round trip that lived in `LegacyPortalApplicationTest`; trailing-slash pin |
| `<Context>PostgresIT` | `postgres:15-alpine` initialised with the module's `initdb.sh`; connects as the service role; the role owns the schema; Flyway V1 applied; column types/lengths/nullability and the `<schema>.<table>_id_seq` sequence match §3–§5; a write/read round trip |

### Strangler cut

In the same stack of commits the package and its tests are `git mv`'d out of legacy-portal,
the context's round trip leaves `LegacyPortalApplicationTest`, the schema leaves the monolith's
H2 URL and `initdb.sql`, and `verify-stage.sh` (which starts every `services/<context>-service`
with a `pom.xml`, exports `<CONTEXT>_URL`, connects it as its own role on PostgreSQL) fails the
stage if the monolith still answers anything but 404 on the extracted context's routes. The
golden transcripts are never re-recorded.

### State after `legacy-portal(announcements)`

| Context | Served by | Port | Schema owner (PostgreSQL) |
|---|---|---|---|
| announcements | `services/announcements-service` (`com.otterworks.announcements`) | 8096 | role `announcements` |
| userpreferences | legacy-portal | 8095 | `legacyportal` |
| feedback | legacy-portal | 8095 | `legacyportal` |
