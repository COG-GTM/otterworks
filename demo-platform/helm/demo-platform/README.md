# demo-platform Helm chart

Deploys the OtterWorks **Demo Platform control plane** into the
`otterworks-platform` namespace on the shared `otterworks-dev` EKS cluster:

- the `otterworks-platform` **namespace**;
- the `demo-ops-dashboard` **ServiceAccount**, annotated with the scoped IRSA
  role `arn:aws:iam::<awsAccountId>:role/otterworks-demo-ops-dashboard-<env>`
  (the role itself is provisioned by `demo-platform/infra/terraform`);
- a **ClusterRole + ClusterRoleBinding** letting that SA manage tenant
  (`otterworks-*`) namespaces and the workloads inside them, plus create runner
  Jobs in `otterworks-platform`;
- the **Ops Dashboard** Deployment + Service + Ingress (`ops.otterworks.app`,
  ingress class `nginx`);
- a templated **Secret** `demo-ops-dashboard` holding `DASHBOARD_PASSCODE` +
  `SESSION_SECRET` (and optionally `DB_PASSWORD` / `JWT_SECRET` /
  `SECRET_KEY_BASE` / `DRIVE_EMAIL` + `DRIVE_PASSWORD`);
- the **reaper v2 CronJob** (runs the runner image with `OP=reap`).

## Prerequisites

- The control-plane IRSA role + DynamoDB control table exist
  (`terraform -chdir=demo-platform/infra/terraform apply`).
- `ingress-nginx` is installed (`scripts/tenant-platform-baseline.sh`).
- Runner + dashboard images pushed to ECR.

## Required values

| Value | Notes |
|---|---|
| `awsAccountId` | 12-digit account id that owns the IRSA role. **Never committed** — templates `fail` if unset. |
| `runnerImage` | `<registry>/otterworks/demo-runner:<tag>` |
| `dashboard.image` | `<registry>/otterworks/demo-ops-dashboard:<tag>` |
| `secret.dashboardPasscode` | required (see below) |
| `secret.sessionSecret` | required (see below) |

## Passing the passcode secret WITHOUT putting it on argv

Never do `--set secret.dashboardPasscode=...` — it lands in your shell history
and the process argv. Use a locked-down values file or `--set-file` instead.

### Option A — `-f secrets.yaml` (git-ignored, chmod 600)

```yaml
# secrets.yaml  (DO NOT COMMIT)
secret:
  dashboardPasscode: "<passcode>"
  sessionSecret: "<random-32-bytes>"
  # optional — enables per-tenant DB drop/create by the reaper + runner Jobs:
  dbPassword: "<rds-app-password>"
  jwtSecret: "<jwt-signing-key>"
  secretKeyBase: "<rails-secret-key-base>"
  # optional — lets `tenant.sh seed <id>` create the per-tenant
  # `retail-drive-seed` Secret itself (see testdata/generated/retail-drive):
  driveEmail: "<drive-account-email>"
  drivePassword: "<drive-account-password>"
```

```bash
umask 077
# generate strong values if you don't have them:
#   openssl rand -hex 16   # passcode
#   openssl rand -hex 32   # session secret

helm upgrade --install demo-platform demo-platform/helm/demo-platform \
  --namespace otterworks-platform --create-namespace \
  --set-string awsAccountId="$AWS_ACCOUNT_ID" \
  --set runnerImage="$RUNNER_IMAGE" \
  --set dashboard.image="$DASHBOARD_IMAGE" \
  -f secrets.yaml

rm -f secrets.yaml   # or keep it 600 in a secrets manager, out of git
```

### Option B — `--set-file` (value read from a file, not the argv)

```bash
printf '%s' "$PASSCODE"       > /tmp/passcode  && chmod 600 /tmp/passcode
printf '%s' "$SESSION_SECRET" > /tmp/session   && chmod 600 /tmp/session

helm upgrade --install demo-platform demo-platform/helm/demo-platform \
  --namespace otterworks-platform --create-namespace \
  --set-string awsAccountId="$AWS_ACCOUNT_ID" \
  --set runnerImage="$RUNNER_IMAGE" \
  --set dashboard.image="$DASHBOARD_IMAGE" \
  --set-file secret.dashboardPasscode=/tmp/passcode \
  --set-file secret.sessionSecret=/tmp/session

shred -u /tmp/passcode /tmp/session
```

### Option C — manage the Secret out of band

Set `--set secret.create=false` and create/rotate the `demo-ops-dashboard`
Secret yourself (e.g. via External Secrets / SOPS). The chart will reference it
by name.

## Validate before deploying

```bash
helm lint demo-platform/helm/demo-platform \
  --set-string awsAccountId=000000000000 \
  --set secret.dashboardPasscode=x --set secret.sessionSecret=y

helm template demo-platform demo-platform/helm/demo-platform \
  --set-string awsAccountId=000000000000 \
  --set secret.dashboardPasscode=x --set secret.sessionSecret=y
```

## Uninstall

```bash
helm uninstall demo-platform -n otterworks-platform
```

The DynamoDB control table + IRSA role are managed by Terraform, not this chart,
so they survive an uninstall (by design — the control table is durable state).
