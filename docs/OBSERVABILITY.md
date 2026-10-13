# Observability on EKS

The local docker-compose stack under `observability/` (Prometheus, Grafana, OTel
Collector, Jaeger, Fluent Bit) is the **source of truth** for rules, dashboards,
collector pipelines and log parsing. This doc describes how the same config runs on
Kubernetes as a **shared platform add-on**: installed once per cluster into the
`monitoring` namespace, never per tenant (AGENTS.md lists monitoring as a shared
platform concern).

Everything here lives in the fork only until it is upstreamed: `infrastructure/helm/**`,
`scripts/deploy-*.sh`, `scripts/lib/**` and `demo-platform/**` are deployed from the
upstream repo.

## Architecture

```
 tenant namespaces (otterworks-<id>, platform/team=otterworks)          monitoring (platform/team=platform)
 ┌──────────────────────────────────────────────┐                  ┌──────────────────────────────────────────┐
 │ service pods ── /metrics ◄────── ServiceMonitor ◄─── selects ─── │ Prometheus (kube-prometheus-stack)       │
 │   │  OTLP http :4318 (observability.otel)    │                  │   ├─ PrometheusRules (ported alerts/rec) │
 │   └──────────────────────────────────────────┼───────────────►  │   └─► Alertmanager ─┬─► platform receivers│
 │ admin-service  ◄── AlertmanagerConfig route ─┼────────────────── │                     └─► tenant routes     │
 │   /api/v1/admin/alerts/ingest (incidents)    │                  │ OTel Collector ─► Jaeger (traces)         │
 │ container stdout ─► /var/log/containers ─────┼─► Fluent Bit DS ─┼─► CloudWatch /otterworks/<env>/<service>  │
 └──────────────────────────────────────────────┘                  │ Grafana (dashboards via sidecar)          │
                                                                    └──────────────────────────────────────────┘
```

| Component | Chart (pinned in `demo-platform/k8s/observability/versions.env`) | Notes |
|---|---|---|
| Prometheus Operator, Prometheus, Alertmanager, Grafana | `prometheus-community/kube-prometheus-stack` 92.3.0 | Selects ServiceMonitors/PodMonitors/PrometheusRules from namespaces labelled `platform/team in (otterworks, platform)`, with any CR label. |
| OpenTelemetry Collector | `open-telemetry/opentelemetry-collector` 0.175.1 | Deployment, contrib image. Port of `observability/otel/otel-collector-config.yml` + `sampling-config.yml` (keep errors, keep >2s, 10% of the rest). Traces → Jaeger (OTLP gRPC), metrics → Prometheus exporter scraped via ServiceMonitor. |
| Jaeger | `jaegertracing/jaeger` 4.16.0, image held at 2.20.0 | All-in-one, in-memory (`max_traces: 100000`). See "Decisions". |
| Fluent Bit | `fluent/fluent-bit` 0.58.3 | DaemonSet tailing `*_otterworks*_*.log` only, `otterworks_json` parser from `observability/logging/parsers.conf`, CloudWatch output via IRSA. |

Source → cluster mapping:

| Local source | Cluster artifact |
|---|---|
| `observability/prometheus/alerts.yml`, `recording_rules.yml` | `generated/prometheus-rules.yaml` (2 PrometheusRule CRs) |
| `observability/grafana/dashboards/*.json` (6) | `generated/grafana-dashboards.yaml` (ConfigMaps labelled `grafana_dashboard: "1"`) |
| `observability/otel/*.yml` | `otel-collector.values.yaml` |
| `observability/jaeger/jaeger-config.yml` | `jaeger.values.yaml` |
| `observability/logging/fluentbit-config.yml`, `parsers.conf` | `fluent-bit.values.yaml` (+ `parsers.conf` passed with `--set-file`) |

`generate.py` makes rules tenant-aware: every `by (...)` aggregation keeps `namespace`
(so one tenant's error spike never alerts as another's), and every alert gets
`affected_service` and `tenant` labels, which admin-service uses for incidents. Re-run it
after editing `observability/`; CI (`.github/workflows/observability-validate.yml`) and the
install script both fail if `generated/` is stale.

## Installing

Shared-cluster installs are cluster-wide changes: get sign-off first (AGENTS.md). The
script refuses non-kind contexts without `--yes`.

```bash
# Render only (no cluster) -- what CI does
demo-platform/scripts/install-observability.sh --env dev --template /tmp/obs

# otterworks-dev (needs sign-off). Secrets come from the environment, never git:
export ALERT_PLATFORM_WEBHOOK_URL=https://<admin-service>/api/v1/admin/alerts/ingest
export ALERT_PLATFORM_WEBHOOK_TOKEN=<admin-service ALERT_WEBHOOK_SECRET>
export ALERT_SLACK_WEBHOOK_URL=<optional>
export JAEGER_BASIC_AUTH="$(htpasswd -nb ops '<password>')"
export FLUENT_BIT_ROLE_ARN="$(terraform -chdir=infrastructure/terraform output -raw fluent_bit_role_arn)"
demo-platform/scripts/install-observability.sh --env dev --context <ctx> --yes
```

Order: kube-prometheus-stack (CRDs) → generated PrometheusRules/dashboards → Jaeger →
OTel Collector → Fluent Bit. The script ends by asserting there is no `LoadBalancer`
Service in `monitoring`.

Terraform (`infrastructure/terraform`, off by default): `enable_observability = true`
creates `modules/observability` -- the Fluent Bit IRSA role (trusted only by
`system:serviceaccount:monitoring:fluent-bit`, write-only to the OtterWorks log groups)
plus the two log groups Fluent Bit routes to that the monitoring module does not create
(`report-service`, `unlabelled`), with the same `log_retention_days`.

Environment overlays live in `demo-platform/k8s/observability/env/<env>/` (receivers,
routes, ingress hosts, retention). Add a directory to add an environment.

## Wiring a tenant

Off by default; existing releases render byte-for-byte the same.

```bash
OBSERVABILITY_ENABLED=true ALERT_WEBHOOK_SECRET=<secret> scripts/deploy-tenant.sh <id>
```

`scripts/lib/tenant-common.sh` then sets, per chart:

- `observability.otel.enabled=true` → injects `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`
  (default `http://otel-collector.monitoring.svc.cluster.local:4318`),
  `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_SERVICE_NAME` (chart name) and
  `OTEL_RESOURCE_ATTRIBUTES` with `k8s.namespace.name`, `service.namespace`,
  `otterworks.tenant` (the tenant namespace) and `k8s.pod.name`, plus any
  `observability.otel.resourceAttributes`.
- admin-service only: `observability.alerting.enabled=true` → an `AlertmanagerConfig`
  that routes this namespace's `critical|warning` alerts to the tenant's own
  `/api/v1/admin/alerts/ingest` with `Authorization: Bearer <ALERT_WEBHOOK_SECRET>`
  (read from the chart's Secret). The operator scopes the route to the namespace, so
  tenants only ever receive their own alerts.

ServiceMonitors stay CRD-gated (`.Capabilities.APIVersions.Has "monitoring.coreos.com/v1"`)
as before; once the stack is installed they are picked up automatically.
`scripts/deploy-dev.sh` labels its namespace `platform/team=otterworks` so the classic dev
deploy is selected too.

## Reaching the UIs

Everything is `ClusterIP`. The only `LoadBalancer` on the cluster is the shared
ingress-nginx (AGENTS.md).

| UI | Port-forward | Shared ingress (`env/dev`) |
|---|---|---|
| Grafana | `kubectl -n monitoring port-forward svc/kps-grafana 3000:80` | `https://grafana.otterworks.app` (Grafana login; admin creds in Secret `grafana-admin`) |
| Jaeger | `kubectl -n monitoring port-forward svc/jaeger 16686:16686` | `https://jaeger.otterworks.app` (nginx basic auth, Secret `jaeger-basic-auth`); also the `Jaeger` datasource in Grafana |
| Prometheus | `kubectl -n monitoring port-forward svc/kps-prometheus 9090` | not exposed |
| Alertmanager | `kubectl -n monitoring port-forward svc/kps-alertmanager 9093` | not exposed |

Grafana ships the 6 OtterWorks dashboards (folder "OtterWorks") next to the
kube-prometheus-stack defaults; filter by the `namespace` variable for one tenant.

## Alert payload contract

Alertmanager's webhook body (`{"alerts": [...]}`) is what
`Api::V1::Admin::AlertsController#ingest` expects. It reads `labels.alertname`,
`labels.severity`, `labels.affected_service` (fallback `service`), `annotations.summary`,
`annotations.description` and `annotations.runbook_url`. Auth is `X-Alert-Secret` or
`Authorization: Bearer`; Alertmanager uses the Bearer form.

## Local validation (kind)

```bash
kind create cluster --name otterworks-obs --image kindest/node:v1.31.0
demo-platform/scripts/install-observability.sh --env kind --context kind-otterworks-obs
docker compose build api-gateway auth-service document-service
docker build -t otterworks-mock-admin:kind demo-platform/k8s/observability/kind/mock-admin
kind load docker-image --name otterworks-obs otterworks-{api-gateway,auth-service,document-service}:latest otterworks-mock-admin:kind
ALERT_PLATFORM_WEBHOOK_URL=http://admin-service.otterworks-kind.svc.cluster.local/api/v1/admin/alerts/ingest \
ALERT_PLATFORM_WEBHOOK_TOKEN=kind-alert-secret \
  demo-platform/scripts/install-observability.sh --env kind --context kind-otterworks-obs
demo-platform/k8s/observability/kind/deploy-tenant-services.sh
kubectl apply -f demo-platform/k8s/observability/kind/test-alert.yaml   # synthetic critical alert
```

The `kind` overlay prints logs to Fluent Bit's stdout instead of CloudWatch and uses a
mock admin-service (`kind/mock-admin`) that enforces the same payload/auth contract.

## Decisions

- **Jaeger all-in-one + in-memory, not production mode.** The collector's tail sampling
  keeps demo volume small; traces are a debugging aid for short-lived tenants and losing
  them on restart is acceptable. Production mode needs Elasticsearch/Cassandra/OpenSearch,
  and a PVC would make Kubernetes create EBS volumes outside Terraform (AGENTS.md: never
  create AWS resources from Kubernetes). Persistent traces should be a deliberate,
  Terraform-owned backend (e.g. managed OpenSearch) later.
- **Jaeger image held at 2.20.0.** Jaeger 2.21 removed the internal `/api/*` HTTP query
  endpoints; Grafana's Jaeger datasource still needs them for search. Unpin once Grafana
  queries Jaeger over `api_v3` by default.
- **Fluent Bit DaemonSet, not Container Insights.** It reuses the repo's parsers and the
  existing `/otterworks/<env>/<service>` log groups and retention from
  `modules/monitoring`, and only tails OtterWorks tenant containers.
- **Install script, not Terraform `helm_release`.** Matches the other
  `demo-platform/scripts/install-*.sh` add-ons and keeps cluster installs out of the
  infra apply path; Terraform only owns the AWS side (IRSA, log groups), default off.
