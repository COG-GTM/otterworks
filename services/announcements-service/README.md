# announcements-service

The announcements bounded context, extracted from the retired `legacy-portal` monolith
([decomposition notes](../../docs/legacy-portal-decomposition.md))
(Spring Boot 3.5, JDK 17). Serves `GET/POST /api/announcements`, `GET /api/announcements/{id}` and
`POST /api/announcements/{id}/publish` on port **8096**, and owns the `announcements` schema through
Flyway (`src/main/resources/db/migration/{h2,postgresql}`). `/health`, error mapping and the
pinned web defaults come from [`portal-common`](../portal-common).

This module is the template the other extracted services follow — see
[§13 of the decomposition notes](../../docs/legacy-portal-decomposition.md#13-extracted-service-template-set-by-announcements-service).

## Build & test

```bash
cd services/portal-parent
./mvnw -B -pl :announcements-service -am verify   # unit tests on H2 + Testcontainers PostgreSQL IT (needs Docker)
```

## Run

```bash
java -jar target/announcements-service.jar          # embedded H2
curl http://localhost:8096/health

# against the tenant PostgreSQL, as its own role (see scripts/initdb.sh)
SPRING_PROFILES_ACTIVE=postgres \
SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:5432/otterworks \
SPRING_DATASOURCE_USERNAME=announcements SPRING_DATASOURCE_PASSWORD=announcements \
java -jar target/announcements-service.jar
```

`make portal-up` runs it with the other two portal services from the root `docker-compose.yml`
against the shared `docker-compose.infra.yml` PostgreSQL (roles and schemas by
`scripts/init-portal-db.sh`, which runs this module's `scripts/initdb.sh`); `make portal-reset`
empties its schema, `make portal-down` stops it.
