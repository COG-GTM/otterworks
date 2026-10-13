# Cross-compile on the build host: compiling the dependency tree under QEMU
# arm64 emulation takes over an hour.
FROM --platform=$BUILDPLATFORM rust:latest AS builder
ARG TARGETARCH
ARG BUILDARCH

RUN apt-get update && apt-get install -y pkg-config libssl-dev && \
    if [ "$TARGETARCH" != "$BUILDARCH" ]; then \
      case "$TARGETARCH" in \
        arm64) apt-get install -y gcc-aarch64-linux-gnu libc6-dev-arm64-cross ;; \
        amd64) apt-get install -y gcc-x86-64-linux-gnu libc6-dev-amd64-cross ;; \
      esac; \
    fi && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in \
      amd64) echo x86_64-unknown-linux-gnu ;; \
      arm64) echo aarch64-unknown-linux-gnu ;; \
      *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac > /rust-target && rustup target add "$(cat /rust-target)"
ENV CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc \
    CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-gcc \
    AR_aarch64_unknown_linux_gnu=aarch64-linux-gnu-ar \
    CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=x86_64-linux-gnu-gcc \
    CC_x86_64_unknown_linux_gnu=x86_64-linux-gnu-gcc \
    AR_x86_64_unknown_linux_gnu=x86_64-linux-gnu-ar
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && \
    cargo build --release --target "$(cat /rust-target)" && rm -rf src

COPY src ./src
RUN touch src/main.rs && cargo build --release --target "$(cat /rust-target)" && \
    cp "target/$(cat /rust-target)/release/file-service" /app/file-service

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y ca-certificates curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/file-service /app/file-service

RUN useradd -r -u 1001 appuser
USER appuser

# demo-coggtm tenant variant -- NEVER merge this to `main`. The tenant runs the
# image this branch builds (tag `tenant-coggtm`), so baking the switch in here is
# the only way to make its uploads fail permanently: it survives pod restarts,
# Redis restarts, TTL expiry and idle-suspend/wake, and needs no chart override:
# the deploy runner renders charts from its own bundled tree, whose file-service
# values are `config: {}` and whose build_helm_args sets a fixed list of
# config.* keys that does not include this one, so nothing overrides the image.
# Anything that does set the variable explicitly still wins -- docker-compose.yml
# passes false, so local stacks behave like the golden app.
ENV FILE_UPLOAD_ALWAYS_FAIL=true

# Click-triggered notification failure (same bake rationale as above): sharing
# a file publishes the file_shared event to a nonexistent SNS topic, so every
# share click fails with a real AWS SNS error and fires the
# NotificationEventPublishFailure alert at admin-service (incident + Devin
# session + Slack, attributed to the sharing user via reporter_email). The
# share record is still saved, but the request returns the AWS error so the
# UI shows a red failure banner. docker-compose.yml passes false, so local
# stacks behave like the golden app.
ENV FILE_SHARE_EVENT_ALWAYS_FAIL=true

# With uploads failing permanently (above), users would have no files to share.
# Seeding gives every user a few demo documents on their first file listing,
# so the share-notification failure is demoable alongside the upload failure.
# docker-compose.yml passes false, so local stacks behave like the golden app.
ENV FILE_SEED_DEMO_DOCS=true

EXPOSE 8082
HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8082/health || exit 1
ENTRYPOINT ["/app/file-service"]
