FROM gradle:8.6-jdk17 AS builder

WORKDIR /app
COPY build.gradle.kts settings.gradle.kts gradle-init.gradle ./
RUN gradle dependencies --no-daemon --init-script gradle-init.gradle || true

COPY src ./src
RUN gradle shadowJar --no-daemon --init-script gradle-init.gradle

FROM eclipse-temurin:17-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/build/libs/*-all.jar app.jar

RUN useradd -r -u 1001 appuser
USER appuser

# Failure switch: when true the SQS consumer polls a nonexistent queue, so
# every ReceiveMessage fails with a real AWS SQS error and fires the
# NotificationConsumerProcessingErrors alert at admin-service. Kept OFF by
# default: the demo's notification failure is the click-triggered share
# variant in file-service (FILE_SHARE_EVENT_ALWAYS_FAIL), and a permanently
# failing background poll would open a competing incident stream. Enable per
# tenant with scripts/inject-bug.sh <id> notification-queue-fail.
ENV NOTIFICATION_SQS_ALWAYS_FAIL=false

EXPOSE 8086
HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8086/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
