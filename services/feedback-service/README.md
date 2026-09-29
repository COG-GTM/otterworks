# feedback-service

The feedback bounded context, extracted from the retired `legacy-portal` monolith
([decomposition notes](../../docs/legacy-portal-decomposition.md))
(Spring Boot 3.5, JDK 17). Serves `POST /api/feedback`, `GET /api/feedback?userId=` and `GET /api/feedback/average-rating`
on port **8098**, and owns the `feedback` schema through Flyway
(`src/main/resources/db/migration/{h2,postgresql}`). `/health`, error mapping and the pinned web
defaults come from [`portal-common`](../portal-common).
`average-rating` keeps the monolith's behaviour: the unrounded in-memory mean of every row
(e.g. `4.333333333333333`), `0.0` when the table is empty.

Follows the extracted-service template in
[§13 of the decomposition notes](../../docs/legacy-portal-decomposition.md#13-extracted-service-template-set-by-announcements-service).

## Build & test

```bash
cd services/portal-parent
./mvnw -B -pl :feedback-service -am verify     # unit tests on H2 + Testcontainers PostgreSQL IT (needs Docker)
```

## Run

```bash
java -jar target/feedback-service.jar            # embedded H2
curl http://localhost:8098/health

# against the tenant PostgreSQL, as its own role (see scripts/initdb.sh)
SPRING_PROFILES_ACTIVE=postgres \
SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:5432/otterworks \
SPRING_DATASOURCE_USERNAME=feedback SPRING_DATASOURCE_PASSWORD=feedback \
java -jar target/feedback-service.jar
```

`make portal-up` runs it with the other two portal services from the root `docker-compose.yml`
against the shared `docker-compose.infra.yml` PostgreSQL (roles and schemas by
`scripts/init-portal-db.sh`, which runs this module's `scripts/initdb.sh`); `make portal-reset`
empties its schema, `make portal-down` stops it.
