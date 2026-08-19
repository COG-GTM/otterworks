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

# DEMO VARIANT (coggtm): permanently break the SQS consumer by pointing it at
# a nonexistent queue, so every ReceiveMessage poll fails with a real AWS SQS
# error and fires the NotificationConsumerProcessingErrors alert at
# admin-service (incident + Devin session). The tenant runs the image this
# branch builds, so baking the switch in here is the only way to make the
# failure permanent: it survives pod restarts, Redis restarts, TTL expiry and
# idle-suspend/wake, and needs no chart override (the deploy runner renders
# charts from its own bundled tree). Anything that sets the variable
# explicitly still wins -- docker-compose.yml passes false, so local stacks
# behave like the golden app.
ENV NOTIFICATION_SQS_ALWAYS_FAIL=true

EXPOSE 8086
HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8086/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
