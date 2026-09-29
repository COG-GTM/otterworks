# Java 17 feedback-service (extracted from legacy-portal). Multi-stage Maven build of the
# portal-parent reactor, non-root JRE runtime. Like legacy-portal it runs on the on-prem / VM
# stack (docker-compose.onprem.yml); it is not on the Helm/EKS deploy path yet.
#
# Build context is services/ (the portal-parent reactor), e.g. from services/feedback-service:
#   docker build -f Dockerfile ..
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /app
COPY portal-parent/pom.xml portal-parent/
# Every module the reactor lists must be present for Maven to read it; only this one's sources are copied.
COPY announcements-service/pom.xml announcements-service/
COPY preferences-service/pom.xml preferences-service/
COPY feedback-service/pom.xml feedback-service/
COPY legacy-portal/pom.xml legacy-portal/
COPY portal-common/pom.xml portal-common/
# Download dependencies first for Docker layer caching.
RUN mvn -B -f portal-parent/pom.xml -pl :feedback-service -am dependency:go-offline

COPY portal-common/src/main/ portal-common/src/main/
COPY feedback-service/src/main/ feedback-service/src/main/
RUN mvn -B -f portal-parent/pom.xml -pl :feedback-service -am package -DskipTests

# JRE 17 runtime.
FROM eclipse-temurin:17-jre-jammy

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/feedback-service/target/feedback-service.jar app.jar

RUN useradd -r -u 1001 appuser
USER appuser

EXPOSE 8098
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8098/health || exit 1

ENTRYPOINT ["java", "-jar", "app.jar"]
