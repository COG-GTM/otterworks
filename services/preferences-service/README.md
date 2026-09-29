# preferences-service

The user-preferences bounded context, extracted from [`legacy-portal`](../legacy-portal/README.md)
(Spring Boot 3.5, JDK 17). Serves `GET /api/preferences/{userId}` and `PUT /api/preferences/{userId}`
on port **8097**, and owns the `user_preferences` schema through Flyway
(`src/main/resources/db/migration/{h2,postgresql}`). `/health`, error mapping and the pinned web
defaults come from [`portal-common`](../portal-common).

Follows the extracted-service template in
[`DECOMPOSITION.md` §13](../legacy-portal/DECOMPOSITION.md#13-extracted-service-template-set-by-announcements-service).

## Build & test

```bash
cd services/portal-parent
./mvnw -B -pl :preferences-service -am verify     # unit tests on H2 + Testcontainers PostgreSQL IT (needs Docker)
```

## Run

```bash
java -jar target/preferences-service.jar            # embedded H2
curl http://localhost:8097/health

# against the tenant PostgreSQL, as its own role (see scripts/initdb.sh)
SPRING_PROFILES_ACTIVE=postgres \
SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:5432/legacyportal \
SPRING_DATASOURCE_USERNAME=preferences SPRING_DATASOURCE_PASSWORD=preferences \
java -jar target/preferences-service.jar
```

The on-prem compose stack in `services/legacy-portal/docker-compose.onprem.yml` runs it next to
the monolith.
