# Java 17 announcements-service (extracted from legacy-portal). Multi-stage Maven build of the
# portal-parent reactor, non-root JRE runtime. Like legacy-portal it runs on the on-prem / VM
# stack (docker-compose.onprem.yml); it is not on the Helm/EKS deploy path yet.
#
# Build context is services/ (the portal-parent reactor), e.g. from services/announcements-service:
#   docker build -f Dockerfile ..
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /app
COPY portal-parent/pom.xml portal-parent/
COPY portal-common/pom.xml portal-common/
COPY announcements-service/pom.xml announcements-service/
# Download dependencies first for Docker layer caching.
RUN mvn -B -f portal-parent/pom.xml -pl :announcements-service -am dependency:go-offline

COPY portal-common/src/main/ portal-common/src/main/
COPY announcements-service/src/main/ announcements-service/src/main/
RUN mvn -B -f portal-parent/pom.xml -pl :announcements-service -am package -DskipTests

# JRE 17 runtime.
FROM eclipse-temurin:17-jre-jammy

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/announcements-service/target/announcements-service.jar app.jar

RUN useradd -r -u 1001 appuser
USER appuser

EXPOSE 8096
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8096/health || exit 1

ENTRYPOINT ["java", "-jar", "app.jar"]
