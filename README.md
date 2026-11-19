# OtterWorks

A collaborative file storage and document editing platform — functionally equivalent to Google Drive + Google Docs. Built as a polyglot microservices system to demonstrate a realistic enterprise technology stack.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/) v2+
- ~12 GB of available RAM (for running all infrastructure and services locally)
- GNU Make (optional, for shorthand commands)
- Runs on both x86_64 and Apple Silicon (ARM64) — no Rosetta required

Individual service development may also require the language toolchains listed in the [Services](#services) table below.

## Quick Start (Local Development)

```bash
# Start infrastructure + all application services (builds images on first run)
make up            # add seed=1 to load sample data once the services are up

# Open the app
open http://localhost:3000        # Web App (React / Vite)
open http://localhost:4200        # Admin Dashboard (Angular)
```

Or without Make:

```bash
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d --build
```

`make infra-up` starts only the infrastructure, for running a service from source against it.

On first run, `scripts/init-db.sql` creates the required Postgres databases and `scripts/localstack-init.sh` provisions S3 buckets, SQS queues, SNS topics, and DynamoDB tables in LocalStack automatically.

To stop everything:

```bash
make down
```

## Services

| Service | Language | Framework | Port | Description |
|---------|----------|-----------|------|-------------|
| API Gateway | Go 1.22 | Chi | 8080 | Request routing, rate limiting, JWT validation |
| Auth Service | Java 17 | Spring Boot 3 | 8081 | Authentication, authorization, user management |
| File Service | Rust 1.77 | Actix-Web 4 | 8082 | File upload/download, S3 integration, versioning |
| Document Service | Python 3.12 | FastAPI | 8083 | Document CRUD, version history, snapshots |
| Collaboration Service | Node.js 20 | Socket.io | 8084 (HTTP + WS) | Real-time collaborative editing (CRDT via Yjs) |
| Notification Service | Kotlin 1.9 | Ktor 2.3 | 8086 | Event-driven notifications (email, in-app, webhook) |
| Search Service | Python 3.12 | Flask 3.0 | 8087 | Full-text search via MeiliSearch |
| Analytics Service | Scala 3.4 | Akka HTTP | 8088 | Usage analytics, data aggregation |
| Admin Service | Ruby 3.3 | Rails 7.1 | 8089 | Admin dashboard backend |
| Audit Service | C# 12 | ASP.NET 8 | 8090 | Immutable audit trail, compliance |
| Report Service *(legacy)* | Java 8 | Spring Boot 2.5 | 8091 | PDF/CSV/Excel report generation (tech-debt: upgrade target Java 17+, Spring Boot 3.2+) |

> **Note:** The Report Service intentionally uses outdated dependencies (Java 8, Spring Boot 2.5, JUnit 4, javax.\*) and is a candidate for a framework-upgrade exercise. See `services/report-service/pom.xml` for details.

The modernization fixtures below run from their own compose files and are not behind the gateway. Their Make targets need a namespace (`NS=<name>`) and offset the host ports per namespace; the ports listed are the compose defaults:

| Fixture | Stack | Port | Description |
|---------|-------|------|-------------|
| Legacy Billing | Python / Flask + PL/pgSQL | 8096 | Billing logic in stored procedures (before state); `make procs-up NS=<name>` |
| Billing Service | Python / FastAPI | 8097 | Extraction target, parity-checked against `procs/` transcripts; `make procs-up NS=<name>` |
| Legacy Portal | Java 11 / Spring Boot | 8095 | Modular monolith for decomposition demos; `services/legacy-portal/docker-compose.onprem.yml` |
| Insurance (Commission Pay) | Oracle PL/SQL | 51521 (host) | `services/industry-solutions/insurance`; `make insurance-up NS=<name>` |

## Frontend Applications

| App | Framework | Port | Description |
|-----|-----------|------|-------------|
| Web App | React 18 / Vite SPA | 3000 | Main user-facing application (served by nginx in production) |
| Admin Dashboard | Angular 17 | 4200 | Administrative interface |
| Mobile (Android/iOS) | Capacitor | — | Native shells wrapping the Web App SPA; see [`frontend/client-app`](frontend/client-app/) |
| Desktop (macOS/Linux/Windows) | Electron | — | Desktop shell wrapping the same SPA (`make dev-electron`) |
| Windows Desktop | WPF / .NET Framework 4.8 | — | Native Windows client for the gateway API; see [`clients/windows-desktop`](clients/windows-desktop/) |

## Architecture

![OtterWorks architecture](docs/diagrams/architecture.png)

- [ARCHITECTURE.md](ARCHITECTURE.md): components, gateway routes, data and event flow, fixtures, deployment.
- [docs/flows.md](docs/flows.md): request-level sequence diagrams.
- [demo-platform/docs/architecture.md](demo-platform/docs/architecture.md): multi-tenant demo platform.
- Diagram source: [docs/diagrams/architecture.dot](docs/diagrams/architecture.dot) (re-render with `docs/diagrams/render.sh`).

## Infrastructure

### AWS Resources (App-Specific)
Managed via Terraform in `infrastructure/terraform/`:
- S3 (file storage, data lake, static assets)
- RDS PostgreSQL
- ElastiCache Redis
- DynamoDB (file metadata, audit events, notifications)
- SQS/SNS (event bus)
- MeiliSearch (full-text search)
- Cognito (identity federation)
- CloudFront (CDN)
- ECR (container image repositories)

### Kubernetes
- Helm charts per service in `infrastructure/helm/`
- Base namespace resources (ResourceQuota, LimitRange) in `infrastructure/k8s/`
- Deploys to EKS cluster managed by [platform-engineering-shared-services](https://github.com/Cognition-Partner-Workshops/platform-engineering-shared-services)

### Deploy to AWS

```bash
# Initialize and apply Terraform
make tf-init
make tf-apply          # uses environments/dev.tfvars

# Deploy services to EKS
make deploy-dev
```

### Tear Down

```bash
make teardown-dev
```

## Observability

All observability services run locally via `docker-compose.infra.yml`.

| Tool | URL | Purpose |
|------|-----|---------|
| Grafana | http://localhost:3001 | Dashboards and metrics visualization (admin / otterworks) |
| Prometheus | http://localhost:9090 | Metrics collection and alerting rules |
| Jaeger | http://localhost:16686 | Distributed tracing UI |
| MeiliSearch | http://localhost:7700 | Search engine dashboard |

- **Logging**: Structured JSON logs → Fluent Bit → CloudWatch (production) / stdout (local)
- **Metrics**: Prometheus scraping `/metrics` endpoints + Grafana dashboards in `observability/grafana/dashboards/`
- **Tracing**: OpenTelemetry SDK per service → OTel Collector → Jaeger
- **Alerting**: PrometheusRule definitions in `observability/prometheus/` → Alertmanager

## CI/CD

GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | Description |
|----------|---------|-------------|
| `ci.yml` | Push / PR to `main` | Lint, test, and build changed services (change-detection via path filters) |
| `security-scan.yml` | Push / PR | SAST, dependency audit, and container scanning |
| `dast-scan.yml`, `deps-remediation.yml`, `equivalence-gate.yml`, `sast-auto-remediate.yml` | See each file | DAST, dependency, behavioural-equivalence and SAST remediation gates (`security/`) |
| `procs-parity.yml` | Changes to billing / `procs/` | Replays recorded stored-procedure transcripts against `billing-service` |
| `docker-build.yml` | Manual (`workflow_dispatch`) | Build and push versioned Docker images to ECR |
| `cd-tenant.yml` | Push to `workshop-*` / `demo-*` | Build and deploy that branch to its demo tenant |
| `mirror-demo.yml` | Push to `main` | Rebase `demo-coggtm` onto `main` |

## Makefile Commands

Run `make help` to list all available commands. Key targets:

| Command | Description |
|---------|-------------|
| `make infra-up` | Start local infrastructure only (Postgres, Redis, LocalStack, MeiliSearch, observability) |
| `make up` | Build and start infrastructure + all application services (`seed=1` to seed) |
| `make down` | Stop all services and infrastructure |
| `make build` | Build all service Docker images |
| `make logs` | Tail logs for all services |
| `make dev-web` | Backend in Docker + client-app web dev server (HMR) on :3000 |
| `make dev-admin` | Backend in Docker + admin dashboard dev server (HMR) on :4200 |
| `make dev-android` | Backend in Docker + build, sync, and run the Android app (Capacitor) |
| `make dev-electron` | Backend in Docker + build and launch the Electron desktop app |
| `make test` | Run tests for all services |
| `make lint` | Lint all services |
| `make test-api-flows` | Cross-service API flow tests against the running stack |
| `make procs-up NS=<name>` / `make procs-parity NS=<name>` | Start the legacy/extracted billing stack / replay parity scenarios |
| `make insurance-up NS=<name>` / `make insurance-test NS=<name>` | Start / test the Oracle insurance fixture |
| `make tf-plan` | Plan Terraform changes (dev) |
| `make deploy-dev` | Deploy all services to dev EKS |
| `make teardown-dev` | Tear down the dev environment |

Per-service build targets are also available (e.g., `make build-gateway`, `make build-auth`).

## Project Structure

```
otterworks/
├── services/              # api-gateway + 10 core services + modernization fixtures
│   ├── api-gateway/       #   Go / Chi
│   ├── auth-service/      #   Java 17 / Spring Boot 3
│   ├── file-service/      #   Rust / Actix-Web
│   ├── document-service/  #   Python / FastAPI
│   ├── collab-service/    #   Node.js / Socket.io + Yjs
│   ├── notification-service/ # Kotlin / Ktor
│   ├── search-service/    #   Python / Flask
│   ├── analytics-service/ #   Scala / Akka HTTP
│   ├── admin-service/     #   Ruby / Rails
│   ├── audit-service/     #   C# / ASP.NET
│   ├── report-service/    #   Java 8 / Spring Boot 2.5 (legacy)
│   ├── legacy-billing/    #   Flask + PL/pgSQL stored procedures (fixture)
│   ├── billing-service/   #   FastAPI extraction target (fixture)
│   ├── legacy-portal/     #   Java 11 modular monolith (fixture)
│   └── industry-solutions/ #  Oracle PL/SQL insurance package (fixture)
├── frontend/
│   ├── client-app/        #   React + Vite web app, Capacitor mobile, Electron desktop
│   └── admin-dashboard/   #   Angular admin console
├── clients/
│   └── windows-desktop/   #   WPF / .NET Framework 4.8 native client
├── procs/                 # Stored-procedure record/replay parity harness
├── etl/                   # Cron-driven Python ETL jobs (etl/scripts, etl/crontab)
├── tests/                 # Cross-service API flow and contract tests
├── infrastructure/
│   ├── terraform/         #   App-specific AWS resources (S3, RDS, DynamoDB, etc.)
│   ├── helm/              #   Per-service Helm charts
│   └── k8s/               #   Base Kubernetes resources (namespace, quotas, limits)
├── platform/terraform/    # Shared VPC, EKS and ECR
├── demo-platform/         # Multi-tenant demo control plane (dashboard, runner, reaper)
├── shared/
│   ├── openapi/           #   OpenAPI specs per service
│   └── events/            #   Event schema definitions (JSON Schema)
├── observability/
│   ├── grafana/           #   Dashboards and provisioning
│   ├── prometheus/        #   Scrape config, alert rules, recording rules
│   ├── jaeger/            #   Jaeger deployment config
│   ├── otel/              #   OpenTelemetry Collector config
│   └── logging/           #   Fluent Bit config and parsers
├── security/              # Trivy, DAST, deps, equivalence gates; network policies
├── scripts/               # Local init, seed, deploy, tenant and teardown scripts
├── docs/                  # Flows, runbooks, plans, architecture diagram source
└── .github/workflows/     # CI/CD pipelines
```

## Contributing

### Getting Started

1. Fork the repository and create a feature branch from `main`.
2. Follow the [Quick Start](#quick-start-local-development) instructions to bring up the local environment.
3. Make your changes in the relevant service or module directory.

### Code Standards

- Each service follows the idiomatic conventions of its language (e.g., `go fmt`, `cargo clippy`, `ruff`, `eslint`).
- Run `make lint` before committing to catch issues early.
- Run `make test` to execute the full test suite.

### Commit Guidelines

- Use clear, descriptive commit messages.
- Keep commits focused — one logical change per commit.

### Pull Requests

1. Push your branch and open a PR against `main`.
2. Ensure CI passes (lint, test, build, security scan).
3. Include a concise description of **what** changed and **why**.
4. Link to any relevant issue or user story.

### Adding a New Service

1. Create a directory under `services/<service-name>/` with a `Dockerfile`.
2. Add the service to `docker-compose.yml` with the shared environment block (`x-common-env`).
3. Create a Helm chart in `infrastructure/helm/<service-name>/`.
4. Add OpenAPI and event schemas to `shared/`.
5. Update this README, `ARCHITECTURE.md` and `docs/diagrams/architecture.dot` (then run `docs/diagrams/render.sh`).

## License

Proprietary - OtterWorks Inc.
