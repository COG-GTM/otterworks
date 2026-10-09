FROM sbtscala/scala-sbt:eclipse-temurin-jammy-17.0.10_7_1.9.9_3.4.1 AS builder

WORKDIR /app
# repo1.maven.org rate-limits shared CI egress IPs (HTTP 429); resolve through Google's
# Maven Central mirror first, falling back to Maven Central itself.
COPY repositories ./
ENV SBT_OPTS="-Dsbt.repository.config=/app/repositories -Dsbt.override.build.repos=true"
COPY build.sbt ./
COPY project/ ./project/
RUN sbt update || true

COPY src ./src
RUN sbt assembly

FROM eclipse-temurin:17-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/scala-3.4.0/analytics-service-assembly-*.jar app.jar

RUN useradd -r -u 1001 appuser
USER appuser

EXPOSE 8088
HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8088/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
