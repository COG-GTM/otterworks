# syntax=docker/dockerfile:1
# Build stage: JDK 21 + Maven
FROM maven:3.9.9-eclipse-temurin-21 AS builder

WORKDIR /app
COPY pom.xml .
# Optional: `docker build --secret id=maven_settings,src=$HOME/.m2/settings.xml` to use a Maven mirror
RUN --mount=type=secret,id=maven_settings,target=/root/.m2/settings.xml,required=false \
    --mount=type=cache,target=/root/.m2/repository \
    mvn -B -q dependency:go-offline

COPY src/ src/
RUN --mount=type=secret,id=maven_settings,target=/root/.m2/settings.xml,required=false \
    --mount=type=cache,target=/root/.m2/repository \
    mvn -B -q package -DskipTests \
    && java -Djarmode=tools -jar target/report-service-modern.jar extract --layers --launcher --destination extracted

# Runtime stage: JRE 21 only, non-root
FROM eclipse-temurin:21-jre

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 appuser \
    && useradd --system --uid 1001 --gid appuser --no-create-home appuser \
    && mkdir -p /tmp/reports \
    && chown appuser:appuser /tmp/reports

WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app/extracted/dependencies/ ./
COPY --from=builder --chown=appuser:appuser /app/extracted/spring-boot-loader/ ./
COPY --from=builder --chown=appuser:appuser /app/extracted/snapshot-dependencies/ ./
COPY --from=builder --chown=appuser:appuser /app/extracted/application/ ./

USER 1001:1001

ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75 -XX:+ExitOnOutOfMemoryError"

EXPOSE 8091

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8091/health || exit 1

ENTRYPOINT ["java", "org.springframework.boot.loader.launch.JarLauncher"]
