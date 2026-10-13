# Infrastructure as Code

OtterWorks' AWS infrastructure is three Terraform roots, all with state in
`s3://otterworks-terraform-state` (us-east-1):

| Root | What it owns | Environments | State keys |
|---|---|---|---|
| `platform/terraform` | VPC, EKS (+ Karpenter IAM), ECR | dev, staging, prod | `platform/terraform.tfstate` (dev), `platform/<env>/terraform.tfstate` |
| `infrastructure/terraform` | RDS, DynamoDB, ElastiCache, S3, SNS/SQS, Cognito, MeiliSearch, IRSA, CloudWatch | dev, staging, prod | `otterworks/terraform.tfstate` (dev), `otterworks/<env>/terraform.tfstate` |
| `demo-platform/infra/terraform` | Demo control plane: control table, dashboard/reaper IAM, DNS, budget, GitHub OIDC roles | dev | `demo-platform/terraform.tfstate` |

`infrastructure/terraform` reads `platform/terraform`'s outputs through
`terraform_remote_state`; its `platform_state_key` variable points it at the
platform state of the same environment.

## Environments

Per-environment **tfvars + partial backend config**, not workspaces:

```
<root>/environments/<env>.tfvars      # sizing and naming
<root>/environments/backend-<env>.hcl # bucket/key/region/encrypt
```

```bash
cd platform/terraform
terraform init -reconfigure -backend-config=environments/backend-staging.hcl
terraform plan -var-file=environments/staging.tfvars
```

Why not workspaces: workspace state lives at `env:/<workspace>/<key>`, so dev
would either have to stay in `default` (and then nothing marks it as dev) or move
its state. Backend files keep dev on exactly the key it has always used, make the
target explicit on every command, and let each environment move to its own
bucket or account later by editing one file.

- **dev** keeps its original keys. `backend-dev.hcl` repeats the key in each
  root's `backend "s3"` block, so `terraform init` with or without it reaches the
  same state and nothing is replaced. The existing scripts
  (`scripts/deploy-dev.sh`, `spinup-dev.sh`, `teardown-*.sh`) keep working
  unchanged.
- **staging** -- NAT, 2 SPOT nodes (max 4), `db.t3.small`, `cache.t3.small`,
  VPC `10.1.0.0/16`.
- **prod** -- NAT, 3 AZs, 3 ON_DEMAND nodes (max 9), `db.r6g.large`, 2-node Redis
  (automatic failover), 365-day log retention, VPC `10.2.0.0/16`.
- ECR repository names are not environment-scoped, so only dev creates them
  (`create_ecr_repositories = false` for staging/prod); set it to true when an
  environment gets its own account.
- `demo-platform` is one control plane per cluster and only exists for
  `otterworks-dev`, so it has dev only.

staging and prod have **never been applied**. They plan offline (below); standing
them up is a separate, reviewed change.

The single list of root/environment pairs the workflows iterate over is
`.github/terraform-environments.json`.

## Checks (no credentials)

`scripts/terraform-check.sh` runs, for every root: `terraform fmt -check`,
`init -backend=false`, `validate`, `tflint` (`.tflint.hcl`, AWS ruleset),
`checkov` (`.checkov.yaml`), and `terraform test` once per
`environments/*.tfvars`. The tests (`<root>/tests/*.tftest.hcl`) are plans against
mocked providers and a stubbed platform state, so each environment's variables
are proven to plan without AWS access.

`.github/workflows/terraform-static.yml` runs the same on every PR/push touching
Terraform and uploads tflint and checkov results as SARIF to code scanning.
`pre-commit install` enables the optional hooks in `.pre-commit-config.yaml`.

**Checkov exceptions** live inline next to the resource, as
`#checkov:skip=<ID>:<reason>`, never in a global skip list. Anything a reviewer
should revisit for prod (Multi-AZ RDS, VPC flow logs, EKS secrets encryption, a
private EKS endpoint, SNS KMS) says so in the reason.

## Workflows that touch AWS

All three are **off by default** and report why in the run summary when they skip.

| Workflow | Trigger | Does | Enabled by |
|---|---|---|---|
| `terraform-plan.yml` | PR touching a root | `plan -lock=false` for each env of each changed root (platform changes also plan `infrastructure`), comment per root/env on the PR, rendered plan as artifact | `TF_PLAN_ENABLED=true`, `TF_PLAN_ROLE_ARN`; same-repo PRs only |
| `terraform-drift.yml` | weekdays 06:17 UTC, manual | `plan -detailed-exitcode` per root/env; opens/updates an issue labelled `terraform-drift`, closes it when clean | `TF_DRIFT_ENABLED=true`, `TF_PLAN_ROLE_ARN` |
| `terraform-apply.yml` | `workflow_dispatch` on `main` only | plan -> encrypted saved plan + sha256 -> **waits for environment `terraform-<env>` approval** -> applies that exact plan | `TF_APPLY_ENABLED=true`, `TF_PLAN_ROLE_ARN`, `TF_APPLY_ROLE_ARN`, secret `TF_PLAN_PASSPHRASE`, environment reviewers |

Secrets used by plans: `TF_VAR_DB_PASSWORD`, `TF_VAR_MEILISEARCH_MASTER_KEY`
(required for prod). The binary saved plan embeds these values, which is why the
apply workflow encrypts it with `TF_PLAN_PASSPHRASE` before uploading and the
plan workflow uploads only the rendered (masked) plan.

Apply is never triggered by a merge. Terraform refuses a saved plan whose state
has moved on, so an approval cannot apply something other than what was shown.

### Why they skip today

The only GitHub OIDC role in the account, `otterworks-github-actions`, is the CD
role. It trusts this fork only for `workshop-*`/`demo-*` refs (see
`demo-platform/infra/terraform/variables.tf`) and only grants ECR push, so it is
neither available to PR branches nor able to plan. The Terraform workflows do not
reuse it.

### Enabling plan/apply

1. **Reviewed trust change.** In `demo-platform/infra/terraform`, set
   `terraform_ci_trusted_repos = ["COG-GTM/otterworks"]` (`iam_terraform_ci.tf`)
   in a PR of its own and apply it through the normal control-plane process. This
   creates:
   - `otterworks-terraform-plan` -- `ReadOnlyAccess` minus data-plane reads
     (DynamoDB items, secrets, SSM, KMS decrypt, S3 objects outside the state
     bucket); trusts `repo:<repo>:pull_request` and `repo:<repo>:ref:refs/heads/main`.
     Fork PRs never receive OIDC tokens.
   - `otterworks-terraform-apply` -- `AdministratorAccess`; trusts only
     `repo:<repo>:environment:terraform-*`, so it can be assumed only by a job
     that already passed the environment's reviewers.
2. Create GitHub Environments `terraform-dev`, `terraform-staging`,
   `terraform-prod` with required reviewers and "deployment branches: main".
3. Set repo variables `TF_PLAN_ROLE_ARN` / `TF_APPLY_ROLE_ARN` (outputs
   `terraform_plan_role_arn` / `terraform_apply_role_arn`) and secrets
   `TF_VAR_DB_PASSWORD`, `TF_VAR_MEILISEARCH_MASTER_KEY`, `TF_PLAN_PASSPHRASE`.
4. Turn on what you want: `TF_PLAN_ENABLED=true`, `TF_DRIFT_ENABLED=true`, and
   only when ready `TF_APPLY_ENABLED=true`. Unset a variable to switch it off.

On this fork none of this changes upstream: the shared account's roles and the
demo control plane are applied from upstream `main`
(`Cognition-Partner-Workshops/otterworks`), so step 1 takes effect only once
upstreamed and applied there.

The state backend has no DynamoDB lock table; plan and drift run with
`-lock=false`, and the apply workflow serializes per root/env with a
`concurrency` group. Adding a lock table (`dynamodb_table` in the backend files)
is a follow-up.
