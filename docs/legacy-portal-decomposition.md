# Legacy portal decomposition inventory

Baseline inventory of `services/legacy-portal` (Java 11, Spring Boot 2.7.18, Spring MVC 5.3.31,
Hibernate 5.6.15, Jackson 2.13.5)
ahead of splitting it into three Spring Boot 3 / Java 21 services:

| Context | Package | Target service | Schema |
|---|---|---|---|
| Announcements | `com.otterworks.legacyportal.announcements` | `announcements-service` | `announcements` |
| User Preferences | `com.otterworks.legacyportal.userpreferences` | `preferences-service` | `user_preferences` |
| Feedback | `com.otterworks.legacyportal.feedback` | `feedback-service` | `feedback` |

The monolith is the parity reference and is not changed by this document. Everything below
was read from source and then confirmed against a running jar (see [How this was
captured](#how-this-was-captured)); request/response examples are verbatim captures, with
only `createdAt` / `timestamp` values being whatever the clock said at capture time.

## Conventions shared by all three contexts

- Port `8095`; all routes are under `/api/<context>` and produce `application/json`.
- Request DTOs are static nested classes inside each controller, validated with
  `javax.validation` (`@Valid @RequestBody`). Primitive fields (`boolean`, `int`) default to
  `false` / `0` when omitted from the JSON body.
- `Instant` fields serialise as ISO-8601 strings with microsecond precision
  (`"2026-09-29T16:40:14.488052Z"`); Boot's default `WRITE_DATES_AS_TIMESTAMPS=false`.
- Error responses come from two different places, and the split matters for parity:

  | Trigger | Produced by | Body |
  |---|---|---|
  | `NoSuchElementException` (unknown announcement id) | `common/GlobalExceptionHandler` | `{"error":"Not Found","message":"<ex message>"}` — 404 |
  | `IllegalArgumentException` **or any exception whose cause is one** (e.g. `NumberFormatException` from a bad path/query param) | `common/GlobalExceptionHandler` | `{"error":"Bad Request","message":"<ex message>"}` — 400 |
  | Bean Validation failure (`MethodArgumentNotValidException`), malformed JSON, missing `@RequestParam`, 404 no-handler, 405 wrong method | Boot `BasicErrorController` / `DefaultErrorAttributes` | `{"timestamp":"…","status":<n>,"error":"<reason>","path":"<uri>"}` |

  The Boot default body has **no `message`, `errors` or `trace`**: Boot 2.7 defaults
  `server.error.include-message=never`, `include-binding-errors=never`,
  `include-stacktrace=never`, and `application.yml` does not override them. So a failed
  constraint never tells the client *which* field failed.
- `FeedbackService.submit` also throws `IllegalArgumentException` for ratings outside 1..5,
  but over HTTP Bean Validation (`@Min(1) @Max(5)`) rejects first, so clients see the Boot
  default 400 body, not the `GlobalExceptionHandler` body. The service-level guard is only
  observable from service tests.

---

## Announcements → `announcements-service`

Source: `announcements/AnnouncementController.java`, `AnnouncementService.java`,
`AnnouncementRepository.java`, `Announcement.java`.

### Routes

| Method | Path | Success | Errors |
|---|---|---|---|
| GET | `/api/announcements?publishedOnly={bool}` (default `true`) | 200 `AnnouncementResponse[]` | 400 GEH `Invalid boolean value [x]` |
| GET | `/api/announcements/{id}` | 200 `AnnouncementResponse` | 404 GEH; 400 GEH for non-numeric id |
| POST | `/api/announcements` | **201** `AnnouncementResponse` | 400 Boot default (validation / malformed JSON) |
| POST | `/api/announcements/{id}/publish` | 200 `AnnouncementResponse` | 404 GEH |

(GEH = `GlobalExceptionHandler` body.) Any other method on these paths → 405 Boot default body.

Ordering: `publishedOnly=true` uses `findByPublishedTrueOrderByCreatedAtDesc()` (newest first);
`publishedOnly=false` uses `findAll()` — **no explicit order** (insertion/id order in practice on
H2 and PostgreSQL). Parity tests must not assert an order for the unfiltered list, or the new
service must deliberately pick one.

### Request / response shapes

`CreateAnnouncementRequest`

| Field | Type | Validation |
|---|---|---|
| `title` | string | `@NotBlank`, `@Size(max = 200)` |
| `body` | string | `@NotBlank`, `@Size(max = 4000)` |
| `published` | boolean | none (omitted → `false`) |

`AnnouncementResponse`: `id` (long), `title`, `body`, `published` (boolean), `createdAt` (ISO instant).

### Examples

`POST /api/announcements`
```http
POST /api/announcements
Content-Type: application/json

{"title":"Maintenance window","body":"Portal read-only Saturday 02:00-04:00 UTC","published":true}
```
```http
HTTP/1.1 201
{"id":1,"title":"Maintenance window","body":"Portal read-only Saturday 02:00-04:00 UTC","published":true,"createdAt":"2026-09-29T16:40:14.488052Z"}
```
Omitting `published` creates a draft:
```http
POST /api/announcements
{"title":"Draft notice","body":"Not yet visible"}

HTTP/1.1 201
{"id":2,"title":"Draft notice","body":"Not yet visible","published":false,"createdAt":"2026-09-29T16:40:14.539768Z"}
```
Validation failure (blank title, or title of 201 chars, or malformed JSON — all identical):
```http
POST /api/announcements
{"title":"","body":"x"}

HTTP/1.1 400
{"timestamp":"2026-09-29T16:40:14.733+00:00","status":400,"error":"Bad Request","path":"/api/announcements"}
```

`GET /api/announcements` (published only, default)
```http
GET /api/announcements

HTTP/1.1 200
[{"id":1,"title":"Maintenance window","body":"Portal read-only Saturday 02:00-04:00 UTC","published":true,"createdAt":"2026-09-29T16:40:14.488052Z"}]
```
```http
GET /api/announcements?publishedOnly=false

HTTP/1.1 200
[{"id":1,"title":"Maintenance window",…,"published":true,…},{"id":2,"title":"Draft notice","body":"Not yet visible","published":false,"createdAt":"2026-09-29T16:40:14.539768Z"}]
```
```http
GET /api/announcements?publishedOnly=maybe

HTTP/1.1 400
{"error":"Bad Request","message":"Invalid boolean value [maybe]"}
```

`GET /api/announcements/{id}`
```http
GET /api/announcements/1

HTTP/1.1 200
{"id":1,"title":"Maintenance window","body":"Portal read-only Saturday 02:00-04:00 UTC","published":true,"createdAt":"2026-09-29T16:40:14.488052Z"}
```
```http
GET /api/announcements/999

HTTP/1.1 404
{"error":"Not Found","message":"announcement 999 not found"}
```
```http
GET /api/announcements/abc

HTTP/1.1 400
{"error":"Bad Request","message":"For input string: \"abc\""}
```

`POST /api/announcements/{id}/publish` (idempotent; no body)
```http
POST /api/announcements/2/publish

HTTP/1.1 200
{"id":2,"title":"Draft notice","body":"Not yet visible","published":true,"createdAt":"2026-09-29T16:40:14.539768Z"}
```
```http
POST /api/announcements/999/publish

HTTP/1.1 404
{"error":"Not Found","message":"announcement 999 not found"}
```

### Entity and DDL (`announcements` schema)

`Announcement` → `announcements.announcement`: `id Long @GeneratedValue(IDENTITY)`,
`title` (not null, 200), `body` (not null, 4000), `published` (not null),
`createdAt Instant` (not null, `updatable=false`, set in the constructor).

Hibernate 5.6 generated DDL (`ddl-auto: update`), PostgreSQL 15 (`postgres` profile), as
created in the database (`pg_dump --schema-only`):
```sql
CREATE TABLE announcements.announcement (
    id bigint NOT NULL,                         -- DEFAULT nextval('announcements.announcement_id_seq')
    body character varying(4000) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    published boolean NOT NULL,
    title character varying(200) NOT NULL,
    CONSTRAINT announcement_pkey PRIMARY KEY (id)
);
CREATE SEQUENCE announcements.announcement_id_seq OWNED BY announcements.announcement.id;
```
(Hibernate emitted this as `id bigserial not null`.) H2 (default profile):
```sql
create table announcements.announcement (
   id bigint generated by default as identity,
   body varchar(4000) not null,
   created_at timestamp not null,
   published boolean not null,
   title varchar(200) not null,
   primary key (id)
);
```

### Tests covering it

- `announcements/AnnouncementServiceTest` (`@DataJpaTest`): `listPublishedReturnsOnlyPublishedNewestFirst`,
  `publishFlipsDraftToPublished`, `getUnknownIdThrows`.
- `LegacyPortalApplicationTest.announcementsModuleRoundTrips` (`@SpringBootTest` + MockMvc): POST → 201 with numeric id, then GET list contains it.
- Not covered by any test: `GET /{id}`, `publishedOnly=false`, validation 400s, the GEH 404 body over HTTP, the publish route over HTTP.

---

## User Preferences → `preferences-service`

Source: `userpreferences/UserPreferenceController.java`, `UserPreferenceService.java`,
`UserPreferenceRepository.java`, `UserPreference.java`.

### Routes

| Method | Path | Success | Errors |
|---|---|---|---|
| GET | `/api/preferences/{userId}` | 200 `PreferenceResponse` (defaults if no row; **never 404**, no row is written) | — |
| PUT | `/api/preferences/{userId}` | 200 `PreferenceResponse` (upsert; full replace) | 400 Boot default |

`userId` is an arbitrary string with no validation on the path variable. The column is
`varchar(100)`, so a PUT with a 101-character id fails at the database and returns **500**
`{"timestamp":…,"status":500,"error":"Internal Server Error","path":…}` (H2 and PostgreSQL);
a GET with the same id still returns 200 defaults.

Defaults (`UserPreferenceService`): `theme="light"`, `locale="en-US"`, `emailNotifications=true`.
Note PUT with `emailNotifications` omitted stores `false` (primitive default), which differs from
the GET default of `true` (captured: `PUT /api/preferences/carol {"theme":"dark","locale":"en-GB"}`
→ 200 `{"userId":"carol","theme":"dark","locale":"en-GB","emailNotifications":false}`).

### Request / response shapes

`UpdatePreferenceRequest`

| Field | Type | Validation |
|---|---|---|
| `theme` | string | `@NotBlank`, `@Size(max = 20)` |
| `locale` | string | `@NotBlank`, `@Size(max = 20)` |
| `emailNotifications` | boolean | none (omitted → `false`) |

`PreferenceResponse`: `userId`, `theme`, `locale`, `emailNotifications`.

### Examples

`GET /api/preferences/{userId}`
```http
GET /api/preferences/alice

HTTP/1.1 200
{"userId":"alice","theme":"light","locale":"en-US","emailNotifications":true}
```

`PUT /api/preferences/{userId}`
```http
PUT /api/preferences/alice
Content-Type: application/json

{"theme":"dark","locale":"fr-FR","emailNotifications":false}
```
```http
HTTP/1.1 200
{"userId":"alice","theme":"dark","locale":"fr-FR","emailNotifications":false}
```
Subsequent `GET /api/preferences/alice` → 200 with the same body. Validation failure (blank
theme, or `"dark-high-contrast-extra"` > 20 chars):
```http
PUT /api/preferences/alice
{"theme":"","locale":"fr-FR"}

HTTP/1.1 400
{"timestamp":"2026-09-29T16:40:14.851+00:00","status":400,"error":"Bad Request","path":"/api/preferences/alice"}
```

### Entity and DDL (`user_preferences` schema)

`UserPreference` → `user_preferences.user_preference`: natural key `userId` (`user_id`,
length 100, assigned — no generator), `theme` (not null, 20), `locale` (not null, 20),
`emailNotifications` (`email_notifications`, not null).

PostgreSQL 15:
```sql
CREATE TABLE user_preferences.user_preference (
    user_id character varying(100) NOT NULL,
    email_notifications boolean NOT NULL,
    locale character varying(20) NOT NULL,
    theme character varying(20) NOT NULL,
    CONSTRAINT user_preference_pkey PRIMARY KEY (user_id)
);
```
H2: identical columns (`varchar`), `primary key (user_id)`. No sequence.

### Tests covering it

- `userpreferences/UserPreferenceServiceTest` (`@DataJpaTest`): `unknownUserGetsDefaults`, `savePersistsAndUpdates`.
- `LegacyPortalApplicationTest.preferencesModuleReturnsDefaults`: GET unknown user → 200, `theme=light`.
- Not covered: PUT over HTTP, validation 400s, the omitted-`emailNotifications` behaviour.

---

## Feedback → `feedback-service`

Source: `feedback/FeedbackController.java`, `FeedbackService.java`, `FeedbackRepository.java`, `Feedback.java`.

### Routes

| Method | Path | Success | Errors |
|---|---|---|---|
| POST | `/api/feedback` | **201** `FeedbackResponse` | 400 Boot default (validation / malformed JSON); 415 Boot default for non-JSON `Content-Type` |
| GET | `/api/feedback?userId={id}` (**required**) | 200 `FeedbackResponse[]`, newest first; `[]` for unknown user | 400 Boot default when `userId` missing |
| GET | `/api/feedback/average-rating` | 200 `{"averageRating": double}` over **all** feedback; `0.0` when empty | — |

### Request / response shapes

`SubmitFeedbackRequest`

| Field | Type | Validation |
|---|---|---|
| `userId` | string | `@NotBlank`, `@Size(max = 100)` |
| `rating` | int | `@Min(1)`, `@Max(5)` (omitted → `0` → fails `@Min`) |
| `message` | string | `@NotBlank`, `@Size(max = 2000)` |

`FeedbackResponse`: `id`, `userId`, `rating`, `message`, `createdAt`.
`AverageRatingResponse`: `averageRating` (double; unrounded arithmetic mean).

### Examples

`POST /api/feedback`
```http
POST /api/feedback
Content-Type: application/json

{"userId":"alice","rating":5,"message":"Great release"}
```
```http
HTTP/1.1 201
{"id":1,"userId":"alice","rating":5,"message":"Great release","createdAt":"2026-09-29T16:40:14.885367Z"}
```
Out-of-range rating (`6` or `0`), missing rating, or blank `userId`/`message` — all identical:
```http
POST /api/feedback
{"userId":"alice","rating":6,"message":"too high"}

HTTP/1.1 400
{"timestamp":"2026-09-29T16:40:14.960+00:00","status":400,"error":"Bad Request","path":"/api/feedback"}
```

`GET /api/feedback?userId=` (after also posting alice/3 and bob/4)
```http
GET /api/feedback?userId=alice

HTTP/1.1 200
[{"id":2,"userId":"alice","rating":3,"message":"Search is slow","createdAt":"2026-09-29T16:40:14.897557Z"},{"id":1,"userId":"alice","rating":5,"message":"Great release","createdAt":"2026-09-29T16:40:14.885367Z"}]
```
```http
GET /api/feedback?userId=nobody

HTTP/1.1 200
[]
```
```http
GET /api/feedback

HTTP/1.1 400
{"timestamp":"2026-09-29T16:40:14.939+00:00","status":400,"error":"Bad Request","path":"/api/feedback"}
```

`GET /api/feedback/average-rating`
```http
GET /api/feedback/average-rating

HTTP/1.1 200
{"averageRating":4.0}
```

### Entity and DDL (`feedback` schema)

`Feedback` → `feedback.feedback`: `id Long @GeneratedValue(IDENTITY)`, `userId`
(`user_id`, not null, 100), `rating int` (not null), `message` (not null, 2000),
`createdAt Instant` (not null, `updatable=false`).

PostgreSQL 15:
```sql
CREATE TABLE feedback.feedback (
    id bigint NOT NULL,                         -- DEFAULT nextval('feedback.feedback_id_seq')
    created_at timestamp without time zone NOT NULL,
    message character varying(2000) NOT NULL,
    rating integer NOT NULL,
    user_id character varying(100) NOT NULL,
    CONSTRAINT feedback_pkey PRIMARY KEY (id)
);
CREATE SEQUENCE feedback.feedback_id_seq OWNED BY feedback.feedback.id;
```
(Hibernate emitted `id bigserial not null`, `rating int4`.) H2: `id bigint generated by default
as identity`, `created_at timestamp`, `rating integer`, same varchar lengths. No index on
`user_id` (the per-user list is a full scan) and no DB check constraint on `rating`.

### Tests covering it

- `feedback/FeedbackServiceTest` (`@DataJpaTest`): `submitAndListForUser`, `averageRatingAcrossAllFeedback`, `rejectsOutOfRangeRating` (service-level `IllegalArgumentException`).
- `LegacyPortalApplicationTest.feedbackModuleValidatesRating`: POST rating 9 → 400 (status only, body not asserted).
- Not covered: GET list / average over HTTP, missing `userId` 400, empty-table `0.0`.

---

## Shared `common` plumbing (copy into each service)

| Piece | What it does | announcements | preferences | feedback |
|---|---|---|---|---|
| `common/HealthController` | `GET /health` → `{"status":"UP","service":"legacy-portal","banner":"<portal.banner>"}` | yes | yes | yes |
| `common/GlobalExceptionHandler` (`@ControllerAdvice`) | 404/400 `{"error","message"}` bodies | yes (404 unknown id, 400 bad id/`publishedOnly`) | yes (only reached via cause-matching of type errors; no direct throw today) | yes (service-level rating guard; bad params) |
| `common/PortalBrandingSettings` | Loads `portal-settings.properties` via Apache Commons Configuration 2.8.0 `FileBasedConfigurationBuilder<PropertiesConfiguration>`; interpolates `${...}` | yes (needed by `/health`) | yes | yes |
| `src/main/resources/portal-settings.properties` | `portal.environment`, `portal.support`, `portal.banner` (interpolates the other two), `portal.classification=${base64Decoder:SU5URVJOQUw=}` | yes | yes | yes |
| Actuator `health,info` exposure + probes (`application.yml`) | `/actuator/health` → `{"status":"UP","groups":["liveness","readiness"]}` | yes | yes | yes |

Maven dependencies each service needs to carry: `spring-boot-starter-web`, `-data-jpa`,
`-validation`, `-actuator`, `commons-configuration2` 2.8.0 (plus the `commons-beanutils` pin
and the Commons Text version decided by the dependency-remediation work, since
`PortalBrandingSettings.interpolate` goes through Commons Text lookups — see
`security/deps/`), `h2` (runtime/tests), `postgresql` (runtime).

`/health` example (any service):
```http
GET /health

HTTP/1.1 200
{"status":"UP","service":"legacy-portal","banner":"OtterWorks Portal (on-prem) - contact portal-support@otterworks.example"}
```
Decision needed per service: `"service"` is hard-coded to `legacy-portal`; parity tests should
either expect the new name or ignore that field.

## Cross-context coupling check

README claim: no cross-context calls, foreign keys or shared tables. Verified:

```console
$ cd services/legacy-portal/src
$ for c in announcements userpreferences feedback; do for o in announcements userpreferences feedback common; do
    [ $c = $o ] && continue
    echo "$c -> $o: $(rg -l "^import com\.otterworks\.legacyportal\.$o\." main/java/com/otterworks/legacyportal/$c | wc -l) files"
  done; done
announcements -> userpreferences: 0 files
announcements -> feedback: 0 files
announcements -> common: 0 files
userpreferences -> announcements: 0 files
userpreferences -> feedback: 0 files
userpreferences -> common: 0 files
feedback -> announcements: 0 files
feedback -> userpreferences: 0 files
feedback -> common: 0 files
$ rg -n "^import com\.otterworks\.legacyportal\.(announcements|userpreferences|feedback)" main/java/com/otterworks/legacyportal/common
(no matches)
$ rg -n -i "@Query|join|nativeQuery|createQuery|@ManyToOne|@OneToMany|@OneToOne|@ManyToMany" main/java
(no matches)
```

- No context package imports another context (all classes within a context are same-package,
  so there are no `com.otterworks.legacyportal.*` imports at all). `common` imports nothing
  from the contexts; contexts reach `common` only through Spring (`@ControllerAdvice` applies
  globally).
- Repositories are derived queries only (`findByPublishedTrueOrderByCreatedAtDesc`,
  `findByUserIdOrderByCreatedAtDesc`, plus `JpaRepository` defaults); no JPQL, native SQL,
  joins or entity associations. The generated DDL has no foreign keys.
- The only implicit link is that `user_preferences.user_preference.user_id` and
  `feedback.feedback.user_id` both hold the same external user id (`varchar(100)`) with no
  constraint between them — safe to split.

## Boot 2.7 → 3 changes that can alter responses

| Area | Boot 2.7 (observed) | Boot 3 / Spring 6 / Hibernate 6 | Parity action |
|---|---|---|---|
| **Trailing-slash matching** | `GET /api/announcements/`, `/api/announcements/1/`, `/api/preferences/alice/`, `/api/feedback/average-rating/` all return **200** with the same body as without the slash (captured). | Spring Framework 6 sets `trailingSlashMatch=false` by default → these become **404** Boot default bodies. | Decide: accept the change (and note it for clients) or restore with a `WebMvcConfigurer` / URL-rewrite filter. Include slash variants in the replay corpus either way. |
| **Hibernate 6 id generation / DDL** | `GenerationType.IDENTITY` on PostgreSQL → `bigserial` (sequence `<table>_id_seq` + column default). Ids start at 1 and increment by 1 per insert. | Hibernate 6's PostgreSQL dialect emits `bigint generated by default as identity` for `IDENTITY`. The sequence semantics are the same, but the DDL differs, so a new schema won't diff-match the monolith's. If anyone switches to `AUTO`/`SEQUENCE`, Hibernate 6 defaults to a per-entity `<entity>_SEQ` with `allocationSize=50` → id gaps and jumps. | Keep `IDENTITY`; create the per-service schemas with explicit DDL (Flyway/Liquibase) instead of `ddl-auto`, and have parity ignore absolute id values or seed identically. |
| **Hibernate 6 `Instant` mapping** | `created_at timestamp without time zone`. | Hibernate 6.2+ maps `Instant` to `timestamp(6) with time zone` by default. | Pin the column type in migrations (or set `hibernate.type.preferred_instant_jdbc_type`) so data copied from the monolith schema round-trips unchanged. |
| **Error attribute defaults** | `/error` body is `{timestamp,status,error,path}`; `message`, `errors`, `trace` excluded (defaults `never`). | Same `server.error.*` defaults, but Spring 6 adds RFC 7807 `ProblemDetail`: if `spring.mvc.problemdetails.enabled=true` (or a `ResponseEntityExceptionHandler` is added) validation/type errors switch to `application/problem+json` `{type,title,status,detail,instance}`. `MethodArgumentNotValidException` etc. now implement `ErrorResponse`, so any new `@ControllerAdvice` that extends `ResponseEntityExceptionHandler` changes these bodies. | Leave problemdetails **off** and don't extend `ResponseEntityExceptionHandler` in the copied `GlobalExceptionHandler`; parity should compare `status,error,path` and ignore `timestamp`. |
| Exception cause matching | `GET /api/announcements/abc` → GEH body `For input string: "abc"` because `@ExceptionHandler(IllegalArgumentException)` matches the `NumberFormatException` cause of `MethodArgumentTypeMismatchException`. | Spring 6 still matches causes, but message text of type-conversion exceptions can change across versions. | Include these cases in the replay corpus; treat `message` text as compared. |
| `javax.*` → `jakarta.*` | `javax.validation`, `javax.persistence`, `javax.annotation.PostConstruct`. | Must be `jakarta.*`; schema-generation properties become `jakarta.persistence.*`. | Mechanical, but required in every copied class. |
| Parameter names | `@PathVariable Long id` / `@RequestParam String userId` rely on names from bytecode. | Spring 6.1 drops `LocalVariableTableParameterNameDiscoverer`; names need `-parameters` (set by `spring-boot-starter-parent`). | Keep the Boot parent, or name every `@PathVariable`/`@RequestParam` explicitly. |

## Existing test-suite behaviour

`./mvnw test -B` (the CI command; locally run as `mvn -B test` under JDK 11 because the wrapper
download was rate-limited): 16 tests, 1 skipped (`DependencyTranscriptEmitterTest`, runs only
when its system properties are set), and in the local run **1 order-dependent failure**:

```
AnnouncementServiceTest.listPublishedReturnsOnlyPublishedNewestFirst:29
Expecting actual: ["second", "first", "Release"]
to contain exactly (and in same order): ["second", "first"]
```

`"Release"` is the row committed by `LegacyPortalApplicationTest.announcementsModuleRoundTrips`
into the shared in-memory H2 database; `AnnouncementServiceTest` passes on its own
(`-Dtest=AnnouncementServiceTest`: 3 run, 0 failures). The failure depends on class execution
order and is left as-is here (monolith behaviour is out of scope); the extracted services' tests
should not share an unscoped in-memory database across test classes.

## How this was captured

```bash
cd services/legacy-portal
JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 mvn -B -DskipTests package
java -jar target/legacy-portal.jar                          # H2, port 8095
# PostgreSQL 15 with scripts/initdb.sql applied:
SPRING_PROFILES_ACTIVE=postgres SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:55432/legacyportal \
  java -jar target/legacy-portal.jar --server.port=8096
pg_dump --schema-only -n announcements -n user_preferences -n feedback
```

The same 37-request curl script was replayed against both the H2 and PostgreSQL instances;
after masking `createdAt`/`timestamp` the two transcripts were identical. Hibernate's
emitted DDL was captured separately with
`javax.persistence.schema-generation.scripts.action=create` (note: setting that property
suppresses `ddl-auto: update`, so it must not be used to start a real instance).
