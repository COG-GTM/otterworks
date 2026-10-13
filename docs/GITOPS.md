# GitOps for the long-lived environments (Argo CD)

OtterWorks has two deployment models that run side by side:

| | Long-lived environments | Ephemeral tenants |
|---|---|---|
| Namespaces | `otterworks-dev`, `otterworks-staging`, `otterworks-prod` | `otterworks-<id>` |
| Driven by | **Argo CD**, reconciling `deploy/gitops/` from git | `scripts/deploy-tenant.sh` (runner, `cd-tenant.yml`) |
| Change = | a merged PR | a push to `workshop-*`/`demo-*`, or a dashboard check-out |
| Lifetime | permanent | TTL label + reaper |
| Hosts | `<env>.otterworks.app`, `api-<env>.…`, `admin-<env>.…` | `t-<id>.demo.otterworks.app`, `api-t-<id>.…` |

Both share the same cluster add-ons (one ingress-nginx and its NLB, cert-manager,
the wildcard certificate) and the same 13 Helm charts with the same release
names, so `<service>-config` / `<service>-secrets` conventions carry over.

**They cannot step on each other.** The Argo CD `AppProject`
(`deploy/gitops/apps/project.yaml`) only allows the three environment namespaces
as destinations, so Argo CD can never create, modify or prune a tenant
namespace. In the other direction, the reaper and idle-suspend only select
namespaces carrying the tenant labels written by `deploy-tenant.sh`, which the
environment namespaces do not have (they get `otterworks.io/environment` and
`app.kubernetes.io/managed-by: argocd`). Do not run `deploy-tenant.sh` with an
id of `dev`, `staging` or `prod`.

## Why Argo CD (not Flux)

- **ApplicationSet** expresses "every service × every environment this cluster
  hosts" in one object, with cluster-level opt-in through annotations. Flux
  needs a Kustomization/HelmRelease per pair or extra templating.
- It renders the existing charts **directly from the repo path** (multi-source
  Applications with `$values` refs). Flux's HelmRelease wants a chart
  repository/OCI artifact or a GitRepository + HelmChart pair per chart.
- A UI that shows sync/health per service per environment is useful for the
  workshop/demo audience this repo serves; Flux has none built in.
- Flux would be the better fit for image-automation-driven promotion; here
  promotion is a reviewed PR by design, so that advantage does not apply.

## Layout

```
deploy/gitops/
  bootstrap/root-app.yaml          app-of-apps root (applied once per cluster)
  apps/project.yaml                AppProject: repo + 3 env namespaces only
  apps/otterworks-envs.yaml        ApplicationSet: clusters x git-files matrix
  apps/otterworks-env-baseline.yaml  ApplicationSet: <env>-baseline per env
  baseline/networkpolicy.yaml      namespace-wide isolation (as deploy-tenant.sh)
  base/values.yaml                 values for every service in every env
  base/services/<svc>.yaml         service.port = container port (as deploy-dev.sh)
  envs/<env>/env-values.yaml       values for every service in one env
  envs/<env>/services/<svc>.yaml   per-service values; image.tag lives here
```

Helm value layering (later wins): chart `values.yaml` → `base/values.yaml` →
`base/services/<svc>.yaml` →
`envs/<env>/env-values.yaml` → `envs/<env>/services/<svc>.yaml` →
`image.repository=<registry>/otterworks/<svc>` (from the cluster annotation).
`scripts/check-image-drift.sh` fails CI if an environment is missing a chart or
lists one that does not exist.

### Cluster opt-in

The ApplicationSet uses a matrix of the **cluster generator** and the **git
files generator**. A cluster participates only when its Argo CD cluster Secret
carries the label `otterworks.io/gitops: "true"`; its annotations choose what it
runs:

| Annotation | Example | Meaning |
|---|---|---|
| `otterworks.io/envs` | `dev`, `{staging,prod}` | environments this cluster hosts (glob) |
| `otterworks.io/services` | `*`, `{api-gateway,web-app}` | service subset (glob) |
| `otterworks.io/image-registry` | `<acct>.dkr.ecr.us-east-1.amazonaws.com` | registry prefix |
| `otterworks.io/git-revision` | `main` | branch/tag the env files are read from |
| `otterworks.io/repo-url` | `https://github.com/COG-GTM/otterworks.git` | repo for charts + env files; must be listed in `apps/project.yaml` `sourceRepos` |

`demo-platform/scripts/install-argocd.sh --bootstrap` writes that Secret for the
in-cluster target and applies the root app. Brace globs need
`applicationsetcontroller.enable.new.git.file.globbing`, which
`demo-platform/k8s/argocd/values.yaml` turns on.

### Secrets and config

Nothing secret is in `deploy/gitops/`. Each environment namespace needs the same
`<service>-secrets` / `<service>-config` objects the scripts create for tenants
(the charts reference them as optional `envFrom`). Create them out of band, or
through the charts' External Secrets support when it lands, before
bootstrapping an environment.

## Promotion: dev → staging → prod

`dev` is the entry point: its `image.tag` values are bumped by hand (or by a
build workflow) in a PR. Staging and prod only change through promotion PRs:

```bash
scripts/gitops-promote.sh dev staging                 # all services
scripts/gitops-promote.sh staging prod api-gateway    # one service
```

The script only copies `image.tag` one step forward, refuses skips (`dev → prod`)
and the mutable tag `latest`, and never contacts a cluster.

The **GitOps promote** workflow (`.github/workflows/gitops-promote.yml`) runs
the same script and opens the PR. It is **off by default**:

- `workflow_dispatch` only, no push/schedule triggers;
- the job is skipped unless the repository variable
  `GITOPS_PROMOTION_ENABLED` is `true`;
- it runs in the GitHub Environment `gitops-promotion`, which should have
  required reviewers;
- "Allow GitHub Actions to create and approve pull requests" must be enabled.

Merging the promotion PR is the deploy: Argo CD auto-syncs the target
environment (`prune` + `selfHeal`). Roll back by reverting the PR.

## Installing on a cluster

**Images first.** Argo CD deploys exactly the `image.tag` in
`envs/<env>/services/<svc>.yaml` from the registry in
`otterworks.io/image-registry`. On this fork nothing publishes `main-<sha>`
tags automatically (`cd-tenant.yml` builds only for the canonical repo's
`main`, and `docker-build.yml` is dispatch-only), so before bootstrapping an
environment make sure those tags exist in the registry -- run
`docker-build.yml` for the commit, or set the env files to tags that do. The
shipped `main-cc23bf1` values are a starting point, not a published release.

```bash
# 1. shared add-ons (pinned in demo-platform/k8s/platform-addons.versions.env)
scripts/tenant-platform-baseline.sh             # ingress-nginx (+ reaper)
demo-platform/scripts/install-cert-manager.sh
demo-platform/scripts/install-argocd.sh

# 2. register the cluster for an environment and apply the app-of-apps
demo-platform/scripts/install-argocd.sh --bootstrap --envs dev \
  --image-registry <acct>.dkr.ecr.us-east-1.amazonaws.com
```

None of this runs from CI. `platform/terraform/modules/platform-addons`
provides the same installs as `helm_release`s (all disabled by default) for when
the platform stack adopts it.

Fork note: on `COG-GTM/otterworks` these files have no effect on the shared
`otterworks-dev` cluster. Charts, deploy scripts and `demo-platform/` take effect
only once upstreamed (see AGENTS.md), and Argo CD is not installed anywhere
until someone runs the steps above.

## Local validation (kind)

The whole path can be rehearsed on kind with no AWS access. The wildcard
certificate comes from a local CA instead of Let's Encrypt; everything else is
the same manifests and values.

```bash
kind create cluster --name otterworks --config <cluster with 80/443 host port mappings>
source demo-platform/k8s/platform-addons.versions.env

# ingress-nginx at the pinned version, hostPort instead of an NLB
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace \
  --version "$INGRESS_NGINX_CHART_VERSION" -f demo-platform/k8s/ingress-nginx/values.yaml \
  --set controller.service.type=NodePort --set controller.hostPort.enabled=true \
  --set controller.publishService.enabled=false \
  --set-string controller.extraArgs.publish-status-address=127.0.0.1 \
  --set-string controller.extraArgs.default-ssl-certificate=ingress-nginx/otterworks-wildcard-tls

demo-platform/scripts/install-cert-manager.sh
kubectl apply -f demo-platform/k8s/dns-tls/local-ca-issuer.yaml
sed -e s/__DOMAIN_ROOT__/otterworks.app/g -e s/__ISSUER__/otterworks-local-ca/g \
  demo-platform/k8s/dns-tls/wildcard-certificate.yaml | kubectl apply -f -

# per-env secrets the charts expect (local throwaway values)
kubectl create ns otterworks-dev
kubectl -n otterworks-dev create secret generic api-gateway-secrets --from-literal=JWT_SECRET=$(openssl rand -hex 24)

# images: build and push to a kind-local registry as otterworks/<svc>:<tag in envs/dev>
demo-platform/scripts/install-argocd.sh --bootstrap --envs dev \
  --services '{api-gateway,web-app,document-service}' \
  --image-registry localhost:5001 --revision <your-branch>

kubectl -n cert-manager get secret otterworks-local-root-ca -o jsonpath='{.data.ca\.crt}' | base64 -d > ca.crt
curl --cacert ca.crt --resolve api-dev.otterworks.app:443:127.0.0.1 https://api-dev.otterworks.app/health
```

`publish-status-address` is kind-only: it gives Ingresses a status address so
Argo CD reports them Healthy (on EKS the NLB hostname fills it in).
