# JDK pinned to an exact Java4Shell (CVE-2026-114938) fixed build; floating 17 tags
# still resolve to affected builds. Guarded by scripts/security/check_java4shell.py.
FROM eclipse-temurin:17.0.21.1_2-jdk-jammy AS builder
# Only the Gradle 8.6 distribution is taken from the gradle image, not its JDK.
COPY --from=gradle:8.6-jdk17 /opt/gradle /opt/gradle
ENV GRADLE_HOME=/opt/gradle PATH=/opt/gradle/bin:$PATH

WORKDIR /app
COPY build.gradle settings.gradle gradle-init.gradle ./
COPY gradle ./gradle
RUN gradle dependencies --no-daemon --init-script gradle-init.gradle || true

COPY src ./src
RUN gradle bootJar --no-daemon --init-script gradle-init.gradle

FROM eclipse-temurin:17.0.21.1_2-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/build/libs/*.jar app.jar

RUN useradd -r -u 1001 appuser
USER appuser

EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=5s CMD curl -f http://localhost:8081/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
