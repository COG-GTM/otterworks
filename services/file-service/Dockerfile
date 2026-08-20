FROM rust:latest AS builder

RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build --release && rm -rf src

COPY src ./src
RUN touch src/main.rs && cargo build --release

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y ca-certificates curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/target/release/file-service /app/file-service

RUN useradd -r -u 1001 appuser
USER appuser

# demo-coggtm tenant variant -- NEVER merge this to `main`. Click-triggered
# notification failure: sharing
# a file publishes the file_shared event to a nonexistent SNS topic, so every
# share click fails with a real AWS SNS error and fires the
# NotificationEventPublishFailure alert at admin-service (incident + Devin
# session + Slack, attributed to the sharing user via reporter_email). The
# share record is still saved, but the request returns the AWS error so the
# UI shows a red failure banner. docker-compose.yml passes false, so local
# stacks behave like the golden app.
ENV FILE_SHARE_EVENT_ALWAYS_FAIL=true

# Seeding gives every user a few demo documents on their first file listing,
# so the share-notification failure is demoable out of the box.
# docker-compose.yml passes false, so local stacks behave like the golden app.
ENV FILE_SEED_DEMO_DOCS=true

EXPOSE 8082
HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8082/health || exit 1
ENTRYPOINT ["/app/file-service"]
