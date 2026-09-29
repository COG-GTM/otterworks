# announcements-service

The announcements bounded context, extracted from [`legacy-portal`](../legacy-portal/README.md)
(Spring Boot 3.5, JDK 17). Serves `GET/POST /api/announcements`, `GET /api/announcements/{id}` and
`POST /api/announcements/{id}/publish` on port **8096**, and owns the `announcements` schema through
Flyway (`src/main/resources/db/migration/{h2,postgresql}`). `/health`, error mapping and the
pinned web defaults come from [`portal-common`](../portal-common).

This module is the template the other extracted services follow — see
[`DECOMPOSITION.md` §13](../legacy-portal/DECOMPOSITION.md#13-extracted-service-template-set-by-announcements-service).

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
SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:5432/legacyportal \
SPRING_DATASOURCE_USERNAME=announcements SPRING_DATASOURCE_PASSWORD=announcements \
java -jar target/announcements-service.jar
```

The on-prem compose stack in `services/legacy-portal/docker-compose.onprem.yml` runs it next to
the monolith.
