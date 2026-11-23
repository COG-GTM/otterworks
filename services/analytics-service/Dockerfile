# JDK pinned to an exact Java4Shell (CVE-2026-114938) fixed build; floating 17 tags
# still resolve to affected builds. Guarded by scripts/security/check_java4shell.py.
FROM eclipse-temurin:17.0.21.1_2-jdk-jammy AS builder
# No sbt image ships a fixed JDK yet, so install the sbt 1.9.9 launcher (checksum-pinned).
ARG SBT_VERSION=1.9.9
ARG SBT_SHA256=c57cae60c2122ca1bba77184dfb4d0d25fc6c18805394ab36ab6208b0c0f262f
RUN curl -fsSL -o /tmp/sbt.tgz https://github.com/sbt/sbt/releases/download/v${SBT_VERSION}/sbt-${SBT_VERSION}.tgz \
    && echo "${SBT_SHA256}  /tmp/sbt.tgz" | sha256sum -c - \
    && tar -xzf /tmp/sbt.tgz -C /opt && rm /tmp/sbt.tgz
ENV PATH=/opt/sbt/bin:$PATH

WORKDIR /app
COPY build.sbt ./
COPY project/ ./project/
RUN sbt update || true

COPY src ./src
RUN sbt assembly

FROM eclipse-temurin:17.0.21.1_2-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/scala-3.4.0/analytics-service-assembly-*.jar app.jar

RUN useradd -r -u 1001 appuser
USER appuser

EXPOSE 8088
HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8088/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
