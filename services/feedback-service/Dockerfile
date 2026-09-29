# Extracted from services/legacy-portal. Spring Boot 3 / Java 17, deployed via
# infrastructure/helm/feedback-service on the shared EKS path.
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /app
COPY pom.xml .
# Download dependencies first for Docker layer caching.
RUN mvn -B dependency:go-offline

COPY src/ src/
RUN mvn -B package -DskipTests

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
