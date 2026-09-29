# Service template — Java 21 / Spring Boot 3

Minimal skeleton that the services extracted from [`legacy-portal`](../legacy-portal)
(`announcements-service`, `preferences-service`, `feedback-service`) are cut from. It is not
deployed on its own.

| Concern | Choice |
|---|---|
| Build | Maven + checked-in wrapper (`./mvnw`, Maven 3.9.9), same as `legacy-portal` |
| Runtime | Java 21, Spring Boot 3.5.x (`spring-boot-starter-parent`) |
| Starters | `web`, `data-jpa`, `validation`, `actuator` |
| Database | PostgreSQL driver; schema owned by **Flyway** (`ddl-auto: validate`, never `update`) |
| Tests | JUnit 5 + Testcontainers PostgreSQL (`@ServiceConnection`); no H2 |
| Image | multi-stage: `maven:3.9-eclipse-temurin-21` → `eclipse-temurin:21-jre-jammy`, uid 1001 |

## Configuration (env only)

The same image runs in docker compose and in Helm; everything is set through the environment.

| Variable | Default | Notes |
|---|---|---|
| `SERVER_PORT` | `8080` | |
| `SPRING_DATASOURCE_URL` | `jdbc:postgresql://localhost:5432/otterworks` | tenant DB `otterworks_<ID>` in EKS |
| `SPRING_DATASOURCE_USERNAME` | none (required) | |
| `SPRING_DATASOURCE_PASSWORD` | none (required) | |
| `SERVICE_DB_SCHEMA` | `service_template` | schema-per-service; Flyway creates it and keeps its history table there, Hibernate uses it as `default_schema` |

## Health / probes

| Path | Use |
|---|---|
| `/livez` (= `/actuator/health/liveness`) | Kubernetes liveness |
| `/readyz` (= `/actuator/health/readiness`) | Kubernetes readiness and the image `HEALTHCHECK`; includes the DB |
| `/actuator/health`, `/actuator/info` | diagnostics |

The `/health` JSON body the other OtterWorks services expose is shared plumbing ported from
`legacy-portal` separately.

JVM memory: like the other JVM services the image passes no heap flags; the container limit
drives the heap. Size the pod like `JVM_SERVICES` in `scripts/lib/tenant-common.sh`
(requests 512Mi, limits 1024Mi / 1 CPU).

## Build, test, run

```bash
cd services/service-template
./mvnw verify                          # compile + smoke test (needs Docker for Testcontainers)
docker build -t otterworks/service-template:dev .
docker run --rm -p 8080:8080 \
  -e SPRING_DATASOURCE_URL=jdbc:postgresql://host.docker.internal:5432/otterworks \
  -e SPRING_DATASOURCE_USERNAME=otterworks -e SPRING_DATASOURCE_PASSWORD=otterworks_dev \
  otterworks/service-template:dev
curl http://localhost:8080/readyz
```

## Cutting a new service

1. Copy this directory to `services/<name>-service` (drop `target/`).
2. Rename `artifactId`, `name` and `finalName` in `pom.xml`, the `COPY --from=builder` jar name
   in the `Dockerfile`, `spring.application.name`, and the Java package
   `com.otterworks.servicetemplate`.
3. Set the `SERVICE_DB_SCHEMA` default to the context's schema (e.g. `announcements`) and the
   port (`server.port`, `EXPOSE`, `HEALTHCHECK`).
4. Replace the `example` package and `V1__create_example_items.sql` with the context's entities
   and a `V1` migration matching the monolith's tables; keep the probe/Flyway assertions in the
   smoke test.
5. Add a job to `.github/workflows/ci.yml` modelled on the `service-template` one.
