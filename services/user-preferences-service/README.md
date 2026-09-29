# user-preferences-service

The **user-preferences** bounded context, extracted from
[`services/legacy-portal`](../legacy-portal) (Spring Boot 2.7 / Java 11) into an
independently deployable Spring Boot 3.3 / Java 17 service.

| | |
|---|---|
| Routes | `GET /api/preferences/{userId}` (defaults for unknown users), `PUT /api/preferences/{userId}` |
| Health | `GET /health`, `/actuator/health/{liveness,readiness}`, `/actuator/prometheus` |
| Port | 8093 |
| Data | owns the `user_preferences` schema (Flyway `db/migration`, Hibernate validates only) |
| Chart | [`infrastructure/helm/user-preferences-service`](../../infrastructure/helm/user-preferences-service) |

## Run and test

```bash
./mvnw verify                                   # unit + slice + full-context tests (Java 17)
./mvnw spring-boot:run                          # H2 in PostgreSQL mode on :8093
SPRING_PROFILES_ACTIVE=postgres \
SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:5432/legacyportal \
  ./mvnw spring-boot:run                        # adopts the legacy database's schema in place
```

Behavioral parity with the monolith is enforced by the transcript harness in
[`parity/legacy-portal`](../../parity/legacy-portal): `make parity-verify CONTEXT=user-preferences`.

## Differences from legacy-portal

- `javax.*` → `jakarta.*` (persistence, validation); Hibernate 6.
- Schema is migration-owned (Flyway) instead of `ddl-auto=update`. `V1` uses
  `CREATE TABLE IF NOT EXISTS` and Flyway baselines, so pointing the service at the
  schema legacy-portal already populated is a no-op migration.
- Branding (`portal-settings.properties`) resolves through Spring placeholders;
  Commons Configuration / Commons Text are no longer on the classpath.
- Trailing-slash matching (on by default in Spring 5.3, off in 6) is re-enabled
  explicitly -- see `platform/LegacyPathMatchingConfig`.
