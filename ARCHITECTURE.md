# OtterWorks Architecture

OtterWorks is a collaborative file storage and document editing platform (functionally equivalent to Google Drive + Google Docs). It is built as a polyglot microservices system to demonstrate a realistic enterprise technology stack with intentional variety across languages, frameworks, and infrastructure patterns.

## System Overview

```
                                    +------------------+
                                    |   CloudFront     |
                                    |   CDN            |
                                    +--------+---------+
                                             |
                                    +--------+---------+
                                    |  NGINX Ingress   |
                                    |  (L7 Router)     |
                                    +--------+---------+
                                             |
                         +-------------------+-------------------+
                         |                                       |
                +--------+---------+                   +---------+--------+
                |  Web Frontend    |                   |  Admin Dashboard |
                |  (React/Next.js) |                   |  (Angular 17)    |
                +--------+---------+                   +---------+--------+
                         |                                       |
                +--------+---------+                             |
                |  API Gateway     +-----------------------------+
                |  (Go / Chi)      |
                +--------+---------+
                         |
     +---+---+---+---+---+---+---+---+---+
     |   |   |   |   |   |   |   |   |   |
  +--+--++--++--++--++--++--++--++--++--++--+
  |Auth ||File||Doc ||Co-||No-||Se-||An-||Ad-||Au-|
  |Svc  ||Svc ||Svc ||lab||tif||arc||aly||min||dit|
  |Java ||Rust||Py  ||JS ||Kt ||Py ||Sc ||Rb ||C# |
  +--+--++--++--++--++--++--++--++--++--++--+
     |   |   |   |   |   |   |   |   |
  +--+---+---+---+---+---+---+---+---+--+
  |         Data & Infrastructure        |
  | PostgreSQL | Redis | DynamoDB | S3   |
  | MeiliSearch | SQS/SNS | Cognito     |
  +-----------------------------------------+
```

## Services

### 1. API Gateway (`services/api-gateway/`)
- **Language**: Go 1.22
- **Framework**: Chi router
- **Purpose**: Central entry point for all client requests. Routes to backend services, handles rate limiting, request logging, CORS, and JWT validation.
- **Port**: 8080
- **Key Patterns**: Middleware chain, reverse proxy, circuit breaker (go-resilience), structured logging (zerolog)

### 2. Auth Service (`services/auth-service/`)
- **Language**: Java 17
- **Framework**: Spring Boot 3.2, Spring Security 6
- **Database**: PostgreSQL (users, roles, sessions)
- **Purpose**: User registration, login, JWT issuance/validation, OAuth2 integration, RBAC, MFA support. Integrates with AWS Cognito for identity federation.
- **Port**: 8081
- **Key Patterns**: Spring Security filter chain, BCrypt hashing, refresh token rotation, Flyway migrations, JPA/Hibernate, Micrometer metrics

### 3. File Service (`services/file-service/`)
- **Language**: Rust 1.77
- **Framework**: Actix-Web 4
- **Database**: DynamoDB (file metadata), S3 (file blobs)
- **Purpose**: File upload (multipart + resumable), download, delete, folder management, file versioning, presigned URL generation. Handles large files efficiently with streaming.
- **Port**: 8082
- **Key Patterns**: Async Rust with Tokio, multipart streaming, AWS SDK for Rust, serde serialization, tower middleware, tracing crate

### 4. Document Service (`services/document-service/`)
- **Language**: Python 3.12
- **Framework**: FastAPI 0.110
- **Database**: PostgreSQL (document metadata, content snapshots)
- **Purpose**: Document CRUD operations, version history, content snapshots, comment threads (including comment resolution), template management. Stores document operational transforms and provides REST API for document metadata.
- **Domain events published**: `document_created`, `document_updated`, `document_deleted`, `comment_added`, `comment_resolved` (SNS fan-out; the notifications SNS-to-SQS subscription is the intended consumer — see the known envelope/attribute gap noted in `services/notification-service/README.md`)
- **Port**: 8083
- **Key Patterns**: Pydantic models, SQLAlchemy async, Alembic migrations, dependency injection, background tasks, structlog

### 5. Collaboration Service (`services/collab-service/`)
- **Language**: Node.js 20 (TypeScript)
- **Framework**: Express 4 + Socket.io 4
- **Database**: Redis (presence, cursors, operational transforms)
- **Purpose**: Real-time collaborative editing via WebSockets. Implements Conflict-free Replicated Data Types (CRDT) for concurrent edits, cursor presence, and typing indicators.
- **Port**: 8084 (HTTP), 8085 (WebSocket)
- **Key Patterns**: CRDT (Yjs), WebSocket rooms, Redis pub/sub for multi-instance sync, Winston logging, event-driven architecture

### 6. Notification Service (`services/notification-service/`)
- **Language**: Kotlin 1.9
- **Framework**: Ktor 2.3
- **Database**: SQS (event queue), SNS (fan-out), DynamoDB (notification history)
- **Purpose**: Processes domain events (file shared, comment added, comment resolved, document edited, user mentioned) and delivers notifications via email (SES), in-app (WebSocket push), and webhook. Event-driven consumer pattern. `comment_resolved` notifies the comment's author, not the document owner.
- **Port**: 8086
- **Key Patterns**: Kotlin coroutines, Ktor routing, SQS long polling, SNS topic subscriptions, Exposed ORM, kotlinx.serialization

### 7. Search Service (`services/search-service/`)
- **Language**: Python 3.12
- **Framework**: Flask 3.0
- **Database**: MeiliSearch (full-text index)
- **Purpose**: Full-text search across documents and file metadata. Indexes content from Document Service and File Service via event-driven ingestion. Supports faceted search, autocomplete, and relevance tuning.
- **Port**: 8087
- **Key Patterns**: MeiliSearch Python client, Flask-RESTful, SQS-based async indexing, marshmallow serialization, gunicorn

### 8. Analytics Service (`services/analytics-service/`)
- **Language**: Scala 3.4
- **Framework**: Akka HTTP
- **Database**: S3 (data lake), Spark (processing)
- **Purpose**: Usage analytics collection (clickstream, API usage), aggregation pipelines, dashboard data API. Processes raw events from SQS into aggregated metrics stored in S3/Parquet.
- **Port**: 8088
- **Key Patterns**: Akka Streams, Spark batch jobs, Parquet columnar storage, circe JSON, cats-effect

### 9. Admin Service (`services/admin-service/`)
- **Language**: Ruby 3.3
- **Framework**: Rails 7.1
- **Database**: PostgreSQL (shared with auth DB, read replicas)
- **Purpose**: Administrative dashboard backend. User management, content moderation, system health overview, feature flags, audit log viewer.
- **Port**: 8089
- **Key Patterns**: ActiveRecord, ActiveAdmin gem, Pundit authorization, Sidekiq background jobs, RSpec testing

### 10. Audit Service (`services/audit-service/`)
- **Language**: C# 12
- **Framework**: ASP.NET 8 Minimal API
- **Database**: DynamoDB (audit events), S3 (long-term archive)
- **Purpose**: Immutable audit trail for all user and system actions. Compliance reporting, data retention policies, GDPR data export/deletion tracking.
- **Port**: 8090
- **Key Patterns**: Minimal API, DynamoDB document model, S3 lifecycle policies, Serilog structured logging, MediatR CQRS, xUnit testing

## Frontend Applications

### 11. Web Frontend (`frontend/web-app/`)
- **Language**: TypeScript 5.4
- **Framework**: React 18 + Next.js 14
- **Purpose**: Main user-facing SPA. File browser, document editor (TipTap/ProseMirror), sharing dialogs, search, notifications panel.
- **Key Patterns**: App Router, Server Components, TanStack Query, Zustand state management, Tailwind CSS, Playwright E2E tests

### 12. Admin Dashboard (`frontend/admin-dashboard/`)
- **Language**: TypeScript 5.4
- **Framework**: Angular 17
- **Purpose**: Admin-facing dashboard. User management, system metrics, audit log viewer, feature flags.
- **Key Patterns**: Standalone components, NgRx signals, Angular Material, RxJS, Karma/Jasmine tests

## Data Infrastructure

### Databases
| Store | Technology | Purpose |
|-------|-----------|---------|
| Primary RDBMS | PostgreSQL 15 (RDS) | Users, documents, admin data |
| Cache/Sessions | Redis 7 (ElastiCache) | Sessions, CRDT state, presence, rate limiting |
| NoSQL | DynamoDB | File metadata, audit events, notification history |
| Search | MeiliSearch 1.6 | Full-text document search, autocomplete |
| Object Storage | S3 | File blobs, document attachments, analytics data lake |
| CDN | CloudFront | Static assets, presigned URL caching |

### Event Bus
- **SQS**: Point-to-point message queues (file events, notification delivery)
- **SNS**: Fan-out topics (domain events published to multiple consumers)
- **Redis Pub/Sub**: Real-time presence and collaboration sync

## Infrastructure

### AWS Resources (App-Specific - in this repo)
Managed via Terraform in `infrastructure/terraform/`:
- S3 buckets (file storage, analytics data lake, static assets)
- RDS PostgreSQL instance
- ElastiCache Redis cluster
- DynamoDB tables (file_metadata, audit_events, notifications)
- SQS queues and SNS topics
- MeiliSearch instance
- Cognito User Pool
- CloudFront distribution
- ECR repositories (one per service)
- IAM roles and policies for EKS service accounts (IRSA)

### Kubernetes (App-Specific - in this repo)
Each service has a Helm chart in `infrastructure/helm/<service-name>/`:
- Deployment, Service, Ingress, NetworkPolicy, ServiceMonitor
- Health probes at `/health`
- Resource limits within namespace quotas
- ConfigMaps and Secrets for service configuration

### Shared Platform (external - `platform-engineering-shared-services`)
- EKS cluster (v1.31, t3.medium nodes)
- VPC, subnets, NAT gateways
- NGINX Ingress Controller
- cert-manager + Let's Encrypt
- Prometheus + Grafana (cluster-wide)
- ArgoCD for GitOps
- ExternalDNS for Route 53
- Network policies (base)

## Observability

### Logging
- Each service uses its language-native structured logging library
- All logs output JSON to stdout (12-factor app pattern)
- Fluentd/Fluent Bit sidecar ships logs to CloudWatch Logs
- Log correlation via trace IDs (OpenTelemetry)

### Metrics
- Each service exposes `/metrics` endpoint (Prometheus format)
- ServiceMonitor CRDs for auto-discovery
- Custom Grafana dashboards in `observability/grafana/dashboards/`
- Key metrics: request rate, error rate, latency (RED), saturation

### Tracing
- OpenTelemetry SDK in each service
- Traces exported to Jaeger (deployed in cluster)
- Distributed trace propagation via W3C TraceContext headers
- Service dependency map generation

### Alerting
- PrometheusRule CRDs for alerting rules
- PagerDuty/Slack integration via Alertmanager
- Runbooks in `docs/runbooks/`

## ETL & Data Pipeline

### Apache Airflow (`etl/airflow/`)
- DAGs for daily/hourly analytics aggregation
- Data quality checks
- S3-to-MeiliSearch document indexing pipeline
- User activity report generation

### Spark Jobs (`etl/spark-jobs/`)
- Scala Spark jobs for heavy analytics processing
- Read from SQS/S3, write Parquet to data lake
- Scheduled via Airflow

## Security

### Application Security
- OWASP Top 10 compliance per service
- Input validation and sanitization
- CORS configuration per-service
- Content Security Policy headers
- Rate limiting at API Gateway
- SQL injection prevention (parameterized queries)

### Infrastructure Security
- Pod security standards (restricted)
- Network policies (default deny)
- Secret management via Kubernetes Secrets + AWS Secrets Manager
- Container image scanning (ECR scan-on-push)
- IRSA (IAM Roles for Service Accounts) - no long-lived credentials in pods

### DevSecOps
- SAST scanning in CI (language-specific linters + Semgrep)
- Dependency auditing (Dependabot, cargo-audit, pip-audit, npm audit)
- Container scanning (Trivy)
- OPA policies for Kubernetes admission control (`security/opa-policies/`)
- SBOM generation per service

## Cost Optimization
- Single RDS instance (multi-schema) instead of per-service databases
- DynamoDB on-demand billing
- S3 Intelligent-Tiering for file storage
- ElastiCache t3.micro for dev
- MeiliSearch on ECS Fargate for dev
- EKS managed node group with spot instances option
- Teardown script to destroy all resources when not in use
- CloudFront caching to reduce origin requests

## Monorepo Structure

```
otterworks/
├── ARCHITECTURE.md                    # This file
├── README.md                          # Project overview and quick start
├── docker-compose.yml                 # Local development orchestration
├── docker-compose.infra.yml           # Local infrastructure (Postgres, Redis, etc.)
├── Makefile                           # Top-level build/deploy commands
├── .github/
│   └── workflows/                     # CI/CD pipelines
│       ├── ci.yml                     # Lint, test, build all services
│       ├── deploy-dev.yml             # Deploy to dev EKS
│       └── security-scan.yml         # SAST/DAST/dependency scanning
├── infrastructure/
│   ├── terraform/                     # App-specific AWS resources
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   ├── modules/
│   │   │   ├── storage/              # S3, CloudFront
│   │   │   ├── database/             # RDS, ElastiCache, DynamoDB
│   │   │   ├── messaging/            # SQS, SNS
│   │   │   ├── search/               # MeiliSearch
│   │   │   ├── auth/                 # Cognito
│   │   │   └── ecr/                  # ECR repositories
│   │   └── environments/
│   │       ├── dev.tfvars
│   │       └── prod.tfvars
│   └── helm/                          # Per-service Helm charts
│       ├── api-gateway/
│       ├── auth-service/
│       ├── file-service/
│       ├── document-service/
│       ├── collab-service/
│       ├── notification-service/
│       ├── search-service/
│       ├── analytics-service/
│       ├── admin-service/
│       └── audit-service/
├── services/
│   ├── api-gateway/                   # Go / Chi
│   ├── auth-service/                  # Java / Spring Boot
│   ├── file-service/                  # Rust / Actix-Web
│   ├── document-service/              # Python / FastAPI
│   ├── collab-service/                # Node.js / Socket.io
│   ├── notification-service/          # Kotlin / Ktor
│   ├── search-service/                # Python / Flask
│   ├── analytics-service/             # Scala / Akka HTTP
│   ├── admin-service/                 # Ruby / Rails
│   └── audit-service/                 # C# / ASP.NET
├── frontend/
│   ├── web-app/                       # React / Next.js
│   └── admin-dashboard/               # Angular 17
├── shared/
│   ├── proto/                         # Protobuf/gRPC service definitions
│   ├── openapi/                       # OpenAPI specs per service
│   └── events/                        # Event schema definitions (JSON Schema)
├── observability/
│   ├── grafana/
│   │   └── dashboards/               # Custom Grafana dashboards
│   ├── prometheus/
│   │   └── rules/                    # PrometheusRule alert definitions
│   ├── jaeger/                        # Jaeger deployment config
│   └── fluentd/                       # Log shipping config
├── security/
│   ├── opa-policies/                  # OPA/Gatekeeper policies
│   ├── scanning/                      # SAST/DAST config files
│   └── sbom/                          # SBOM generation scripts
├── etl/
│   ├── airflow/
│   │   └── dags/                      # Airflow DAG definitions
│   └── spark-jobs/                    # Scala Spark processing jobs
├── scripts/
│   ├── setup-local.sh                 # Local dev environment setup
│   ├── deploy-dev.sh                  # Deploy all services to dev
│   ├── teardown-dev.sh                # Tear down dev environment
│   └── seed-data.sh                   # Seed development data
└── docs/
    ├── api/                           # API documentation
    ├── runbooks/                      # SRE runbooks
    └── adr/                           # Architecture Decision Records
```
