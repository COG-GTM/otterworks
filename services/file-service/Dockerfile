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

# Seeding gives every user a few demo documents on their first file listing, so
# a brand-new account has something to share without uploading first.
# docker-compose.yml passes false, so local stacks behave like the golden app.
ENV FILE_SEED_DEMO_DOCS=true

EXPOSE 8082
HEALTHCHECK --interval=10s --timeout=3s CMD curl -f http://localhost:8082/health || exit 1
ENTRYPOINT ["/app/file-service"]
