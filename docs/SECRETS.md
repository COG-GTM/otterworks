# Secrets delivery (External Secrets Operator)

How OtterWorks application secrets and config get from Terraform into pods
when External Secrets Operator (ESO) is enabled, and how the older
deploy-time path still works when it is not. ESO is **opt-in**: everything
below is off by default, so existing deploys are unchanged until someone turns
it on.

## The flow

```
Terraform (infrastructure/terraform, enable_external_secrets = true)
  ├─ random_password ─┐
  ├─ var.db_password ─┼─▶ AWS Secrets Manager   otterworks/<env>/<service>/<KEY>
  └─ module outputs ──┴─▶ SSM Parameter Store  /otterworks/<env>/<service>/<KEY>
                                   │
                                   ▼   (IRSA: role otterworks-external-secrets-<env>, read-only)
External Secrets Operator (namespace external-secrets, shared, once per cluster)
  ClusterSecretStore otterworks-secretsmanager / otterworks-parameterstore
                                   │
                                   ▼   ExternalSecret <release>-external-secrets (per chart)
Kubernetes Secret <release>-external-secrets  (owned by the ExternalSecret)
                                   │
                                   ▼   envFrom (after <release>-config and <release>-secrets)
Pod env vars (JWT_SECRET, SPRING_DATASOURCE_PASSWORD, DOC_SVC_DATABASE_URL, ...)
```

| Piece | Where |
|---|---|
| Secrets/params + ESO IRSA role | `infrastructure/terraform/modules/secrets`, wired by `infrastructure/terraform/secrets.tf` |
| ESO install (pinned chart) | `demo-platform/scripts/install-external-secrets.sh` |
| ClusterSecretStores | `demo-platform/k8s/external-secrets/cluster-secret-stores.yaml` |
| Per-service mapping | `externalSecrets:` in each `infrastructure/helm/<svc>/values.yaml`, rendered by `templates/externalsecret.yaml` |
| Deploy opt-in | `USE_EXTERNAL_SECRETS=true` for `scripts/deploy-dev.sh` / `scripts/deploy-tenant.sh` (helpers in `scripts/lib/external-secrets.sh`) |

### Naming convention

* Secrets Manager: `otterworks/<env>/<service>/<KEY>`, plain-string value.
* SSM Parameter Store: `/otterworks/<env>/<service>/<KEY>`, type `String`
  (non-sensitive config only: table/bucket names, topic ARNs, region).
* `<KEY>` is the canonical name of the value (`JWT_SECRET`, `DB_PASSWORD`, ...).
  The chart maps it to whatever env var the service actually reads, so one
  vaulted `DB_PASSWORD` becomes `SPRING_DATASOURCE_PASSWORD` +
  `SPRING_FLYWAY_PASSWORD` for auth-service, `DATABASE_PASSWORD` for
  admin/analytics and `DB_PASSWORD` for report-service.
* Each service gets its own copy of shared values (e.g. `JWT_SECRET`) so IAM or
  store-level scoping per service is possible later without renaming.

### What is vaulted

| Service | Secrets Manager keys | SSM keys |
|---|---|---|
| api-gateway | JWT_SECRET | |
| auth-service | JWT_SECRET, DB_PASSWORD | COGNITO_USER_POOL_ID, COGNITO_WEB_CLIENT_ID, COGNITO_ADMIN_CLIENT_ID (vaulted, not mapped: no service reads them yet) |
| file-service | ALERT_WEBHOOK_SECRET | AWS_REGION, S3_BUCKET, DYNAMODB_TABLE, DYNAMODB_{FOLDERS,VERSIONS,SHARES}_TABLE, SNS_TOPIC_ARN |
| document-service | JWT_SECRET, DB_PASSWORD (+ `DOC_SVC_DATABASE_URL` templated from it) | DOC_SVC_AWS_REGION, DOC_SVC_SNS_TOPIC_ARN |
| collab-service | JWT_SECRET | |
| notification-service | ALERT_WEBHOOK_SECRET | AWS_REGION, DYNAMODB_TABLE_NOTIFICATIONS, SNS_TOPIC_ARN, SQS_QUEUE_URL |
| search-service | MEILISEARCH_API_KEY | |
| analytics-service | DB_PASSWORD | AWS_REGION, S3_DATA_LAKE_BUCKET |
| admin-service | JWT_SECRET, DB_PASSWORD, SECRET_KEY_BASE, ALERT_WEBHOOK_SECRET | |
| audit-service | | Aws__Region, Aws__DynamoDbTable, Aws__S3ArchiveBucket |
| report-service | DB_PASSWORD | |
| web-app, admin-dashboard | (none; `externalSecrets.enabled` renders nothing) | |

`JWT_SECRET`, `SECRET_KEY_BASE`, `ALERT_WEBHOOK_SECRET` and (when
`meilisearch_master_key` is empty) `MEILISEARCH_API_KEY` are generated with
`random_password`. `DB_PASSWORD` is the existing `db_password` Terraform input
(passed as `TF_VAR_db_password`, never in tfvars). No value is committed to git.

Values that depend on how a release is deployed stay in the chart's ConfigMap
from the deploy scripts: DB host/ports (PgBouncer vs. direct), DB user/name,
in-cluster Redis/MeiliSearch URLs, feature toggles.

## Authentication: IRSA only

The ESO controller ServiceAccount `external-secrets/external-secrets` is
annotated with the role from `terraform output external_secrets_role_arn`. The
role:

* trusts only `system:serviceaccount:external-secrets:external-secrets` on the
  cluster's OIDC provider (`StringEquals` on `sub` and `aud`);
* allows only `secretsmanager:GetSecretValue`/`DescribeSecret` on
  `secret:otterworks/<env>/<service>/*` and `ssm:GetParameter(s)`/`GetParametersByPath`
  on `parameter/otterworks/<env>/<service>/*`, one ARN pattern per service the
  module writes. No writes, and no other secrets in the account: e.g. the RDS
  admin secret `otterworks/dev/rds/master` and the MeiliSearch master key
  `otterworks/dev/meilisearch-master-key` are not readable by ESO.

There are no static keys anywhere. Store `conditions` only restrict *which
namespaces* may reference a store, not *which keys* they request, so the stores
are split by trust level:

| Store | Namespaces | AWS identity | Can read |
|---|---|---|---|
| `otterworks-secretsmanager` | golden only (`GOLDEN_NAMESPACE`, default `otterworks`) | controller IRSA role | all `otterworks/<env>/<service>/*` secrets |
| `otterworks-parameterstore` | golden only | controller IRSA role | all `/otterworks/<env>/<service>/*` parameters |
| `otterworks-tenant-secretsmanager` | `^otterworks-[a-z0-9-]+$` (tenants) | assumes `external_secrets_tenant_role_arn` | only `otterworks/<env>/<service>/DB_PASSWORD` |

So a tenant ExternalSecret can never sync the golden `JWT_SECRET`,
`SECRET_KEY_BASE` or webhook secret, even if someone writes one by hand. The
tenant role trusts only the controller role (`sts:AssumeRole`), and the
controller role may assume only that role.

## Enabling it (operators)

Merging this code applies nothing. To turn it on for a cluster (each step is a
deliberate, reviewed action; none run from CI):

1. **Vault the values + create the role**:
   `cd infrastructure/terraform && TF_VAR_db_password=... terraform apply -var enable_external_secrets=true`
   (or `USE_EXTERNAL_SECRETS=true ./scripts/deploy-dev.sh`, which passes
   `TF_VAR_enable_external_secrets` through its normal Terraform step).
2. **Install ESO once per cluster**:
   `ESO_ROLE_ARN=$(terraform -chdir=infrastructure/terraform output -raw external_secrets_role_arn) ESO_TENANT_ROLE_ARN=$(terraform -chdir=infrastructure/terraform output -raw external_secrets_tenant_role_arn) demo-platform/scripts/install-external-secrets.sh`
   (`--dry-run` renders the chart and stores without touching the cluster).
3. **Deploy with the opt-in**:
   `USE_EXTERNAL_SECRETS=true ./scripts/deploy-dev.sh --skip-terraform` or
   `USE_EXTERNAL_SECRETS=true ./scripts/deploy-tenant.sh <ID>`.
   Both run a read-only preflight (CRD present, their stores `Ready`) and refuse
   to deploy otherwise. Dashboard-launched tenant deploys need the ESO rules in
   `demo-platform/helm/demo-platform/templates/rbac.yaml` (read the CRD and the
   tenant store, manage ExternalSecrets).

**Staying enabled.** Once the state holds the ESO role, `deploy-dev.sh` and
`spinup-dev.sh` keep `enable_external_secrets=true` even without
`USE_EXTERNAL_SECRETS` (`eso_tf_enabled` in `scripts/lib/external-secrets.sh`),
so a routine apply never deletes keys running pods sync from. When applying
Terraform by hand, set `enable_external_secrets = true` in your tfvars.
Disabling is a deliberate `terraform apply -var enable_external_secrets=false`
after redeploying without the opt-in.

With the opt-in, `deploy-dev.sh` stops writing JWT/DB/Rails secrets into the
Helm values file entirely, so the chart's `<release>-secrets` Secret is no
longer rendered (Helm removes it on upgrade). `deploy-tenant.sh` only moves the
**shared RDS credential** to ESO; each tenant keeps its own generated
`JWT_SECRET`/`SECRET_KEY_BASE` in `<release>-secrets` (the tenant values null out
`JWT_SECRET`, `SECRET_KEY_BASE`, `ALERT_WEBHOOK_SECRET`, `MEILISEARCH_API_KEY`
and all SSM parameters, since tenants use their own Redis/MeiliSearch and
prefixed storage).

Unset `USE_EXTERNAL_SECRETS` to fall back to the previous path at any time.

## The fallback path (default)

Without the opt-in the deploy scripts behave as before: secret pairs are
collected in `SECRET_KV`, written to a `chmod 600` temp values file and passed
with `helm -f` (never on argv), rendered into `<release>-secrets`, and envFrom'd
into the pod. Values are fixed at deploy time.

## Rotation

* ESO re-reads every key each `externalSecrets.refreshInterval` (default `1h`)
  and updates the Kubernetes Secret in place. Force an immediate sync with
  `kubectl annotate externalsecret <release>-external-secrets force-sync=$(date +%s) --overwrite`.
* Env vars are read at process start, so **pods must be restarted** to pick up a
  new value: `kubectl rollout restart deploy/<release>`.
* Rotating a generated value: `terraform apply -replace=module.secrets[0].random_password.jwt_secret`
  (all services that share it change together), then force-sync and restart
  the affected releases. Rotate `DB_PASSWORD` by changing RDS and
  `TF_VAR_db_password` together.

## Adding a secret (or config) for a service

1. Terraform: add `KEY = <value or random_password>` under the service in
   `local.service_secrets` (`modules/secrets/main.tf`) for sensitive values, or
   under the service in `service_config` (`secrets.tf`) for non-sensitive
   config. The IAM policy already covers the whole `otterworks/<env>/` prefix.
2. Chart: in `infrastructure/helm/<service>/values.yaml` add
   `ENV_VAR_THE_SERVICE_READS: KEY` under `externalSecrets.secrets` (Secrets
   Manager) or `externalSecrets.parameters` (SSM). For values built from
   secrets (connection strings) add an ESO v2 template under
   `externalSecrets.templates`, e.g.
   `DATABASE_URL: "postgres://user:{{ .DB_PASSWORD | urlquery | replace \"+\" \"%20\" }}@host/db"`
   (`urlquery` encodes a space as `+`, which database URL parsers keep literally).
3. Keep the fallback working: add the matching `add_secret` / `config.*` wiring
   in `scripts/deploy-dev.sh` / `scripts/lib/tenant-common.sh`.
4. Validate locally: `helm template <svc> infrastructure/helm/<svc> --set image.tag=t --set externalSecrets.enabled=true`.

A brand-new service chart: copy `templates/externalsecret.yaml` verbatim, add
the `externalSecrets:` block to `values.yaml` (with `service: <name>`), and add
the guarded `secretRef` for `<release>-external-secrets` to the Deployment's
`envFrom`.

## Local development (docker-compose)

`docker-compose.yml` intentionally keeps hard-coded **test-only** credentials
(`AWS_ACCESS_KEY_ID: test`, `POSTGRES_PASSWORD: otterworks_dev`, the default
`JWT_SECRET`, ...) against LocalStack and local containers. They are not used by
any cluster and are not part of this flow; do not reuse them anywhere real.

## Troubleshooting

```bash
kubectl get clustersecretstore                     # READY=True, STATUS=Valid
kubectl -n <ns> get externalsecret                 # STATUS=SecretSynced
kubectl -n <ns> describe externalsecret <release>-external-secrets
kubectl -n external-secrets logs deploy/external-secrets
```

* Store not Ready / `AccessDenied`: IRSA annotation or role trust is wrong
  (namespace/SA name), or the key is outside `otterworks/<env>/`.
* `SecretSyncedError ... not found`: the key was not written by Terraform
  (check `terraform output` / `enable_external_secrets`).
* Pod in `CreateContainerConfigError`: the target Secret does not exist yet
  (the ExternalSecret has not synced); the envFrom for it is intentionally not
  optional so a pod never starts without its secrets.
