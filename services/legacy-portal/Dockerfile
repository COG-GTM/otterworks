# Java 17. Maven build, matching the legacy Java enterprise pattern.
# NOTE: legacy-portal deploys to a VM / on-prem host today (see docker-compose.onprem.yml,
# scripts/run-onprem.sh, deploy/legacy-portal.service). It is intentionally NOT on the Helm/EKS
# deploy path — it is the rehost / decomposition "before" state.
#
# Build context is services/ (the portal-parent reactor), e.g. from services/legacy-portal:
#   docker build -f Dockerfile ..
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /app
COPY portal-parent/pom.xml portal-parent/
# Every module the reactor lists must be present for Maven to read it; only this one's sources are copied.
COPY announcements-service/pom.xml announcements-service/
COPY preferences-service/pom.xml preferences-service/
COPY legacy-portal/pom.xml legacy-portal/
COPY portal-common/pom.xml portal-common/
# Download dependencies first for Docker layer caching.
RUN mvn -B -f portal-parent/pom.xml -pl :legacy-portal -am dependency:go-offline

COPY portal-common/src/main/ portal-common/src/main/
COPY legacy-portal/src/ legacy-portal/src/
RUN mvn -B -f portal-parent/pom.xml -pl :legacy-portal -am package -DskipTests

# JRE 17 runtime.
FROM eclipse-temurin:17-jre-jammy

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/legacy-portal/target/legacy-portal.jar app.jar

RUN useradd -r -u 1001 appuser
USER appuser

EXPOSE 8095
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8095/health || exit 1

ENTRYPOINT ["java", "-jar", "app.jar"]
