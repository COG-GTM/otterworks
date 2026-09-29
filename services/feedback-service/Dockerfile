# syntax=docker/dockerfile:1
# Extracted from services/legacy-portal. Spring Boot 3 / Java 17, deployed via
# infrastructure/helm/feedback-service on the shared EKS path.
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /app
COPY pom.xml .
# Dependencies resolve into a BuildKit cache. An optional `maven-settings` secret lets a
# build use an internal mirror without baking credentials into a layer:
#   docker build --secret id=maven-settings,src=$HOME/.m2/settings.xml .
RUN --mount=type=cache,target=/root/.m2/repository \
    --mount=type=secret,id=maven-settings,target=/root/.m2/settings.xml \
    mvn -B dependency:go-offline

COPY src/ src/
RUN --mount=type=cache,target=/root/.m2/repository \
    --mount=type=secret,id=maven-settings,target=/root/.m2/settings.xml \
    mvn -B package -DskipTests

FROM eclipse-temurin:17-jre-jammy

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/target/feedback-service.jar app.jar

RUN useradd -r -u 1001 appuser
USER appuser

EXPOSE 8094
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8094/health || exit 1

ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar app.jar"]
