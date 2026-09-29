---
name: synthetic-testdata-generation
description: >
  Repo-specific mechanics for generating and validating synthetic test data in
  OtterWorks. Covers schema layout, namespacing, validation commands, and the
  exact Makefile targets needed to run the verification loop.
---

# Synthetic Test-Data Generation — OtterWorks

This skill provides the repo-specific mechanics that the
`!generate-testdata` Playbook relies on. It is auto-loaded when Devin works
in this repository.

## Database Schema Location

- **Auth service** (Flyway): `services/auth-service/src/main/resources/db/migration/V*.sql`
  - `users`, `user_roles`, `refresh_tokens`, `user_settings`
- **Admin service** (Rails): `services/admin-service/db/schema.rb`
  - `admin_users`, `storage_quotas`, `audit_logs`, `feature_flags`,
    `announcements`, `incidents`, `system_configs`
- **Namespaced DDL**: `testdata/harness/create_schema.sql`
  (creates all tables under `otterworks_<ns>`)

## Valid Enum Values

| Table | Column | Valid values |
|-------|--------|-------------|
| `user_roles` | `role` | USER, EDITOR, ADMIN, OWNER |
| `admin_users` | `role` | viewer, editor, admin, super_admin |
| `admin_users` | `status` | active, suspended, deactivated |
| `incidents` | `severity` | low, medium, high, critical |
| `incidents` | `status` | open, investigating, resolved, closed |
| `storage_quotas` | `tier` | free, basic, pro, enterprise |
| `announcements` | `severity` | info, warning, critical |
| `announcements` | `status` | draft, active, expired |

## FK Relationships

```
users.id  <──  user_roles.user_id
users.id  <──  user_settings.user_id
users.id  <──  refresh_tokens.user_id
admin_users.id  <──  storage_quotas.user_id
admin_users.id  <──  audit_logs.actor_id  (nullable)
```

## Business Rules

- `storage_quotas.used_bytes` must be `<= quota_bytes`
- `audit_logs.created_at` must be `>= admin_users.created_at` for the referenced
  `actor_id` (temporal consistency)
- `users.email` and `admin_users.email` must be unique within their table
- `refresh_tokens.expires_at` must be after `refresh_tokens.created_at`

## Namespacing Convention

Every run writes to schema `otterworks_<NS>` where NS is provided by the user.
Examples: `otterworks_dev`, `otterworks_qa1`, `otterworks_loadtest`,
`otterworks_session1`.

Namespaces isolate concurrent runs — multiple Devin sessions (or child sessions)
can generate data in parallel without collision.

## Commands

```bash
# Create a namespace schema with all tables
make testdata-setup-schema NS=dev

# Run the generated data script (path depends on what you produce)
python testdata/generated/dev/generate.py --ns dev

# Validate the data (standard checks + optional criteria file)
make testdata-validate NS=dev
make testdata-validate NS=dev CRITERIA=testdata/generated/dev/criteria.json

# Drop the namespace schema (full cleanup)
make testdata-clean NS=dev
```

## Generated Script Layout

Place generated scripts at:
```
testdata/generated/<ns>/
├── generate.py       # main data-generation script
├── criteria.json     # machine-checkable acceptance criteria
└── simulate.py       # optional: activity-simulation over time
```

## Connection Defaults (local Docker)

| Variable | Default |
|----------|---------|
| `DB_HOST` | `localhost` |
| `DB_PORT` | `5432` |
| `DB_NAME` | `otterworks` |
| `DB_USER` | `otterworks` |
| `DB_PASSWORD` | `otterworks_dev` |

On EKS/RDS, set these to the cluster values. The validation harness and scripts
all read from environment variables.

## Existing Seed Reference

- `scripts/seed.py` — populates 10 users + quotas + audit logs + feature flags
  into the default schema. Use as a structural reference for how the data fits
  together (UUIDs, timestamps, relationships).

## Legacy Seed Generators (testdata/legacy/)

Deterministic multi-store seeders for migration demos (Postgres + DynamoDB +
S3 on LocalStack). Run via uv (inline script deps — no venv needed):

```bash
make infra-up                          # postgres:5432 + localstack:4566 (if host postgres holds 5432: sudo systemctl stop postgresql postgresql@14-main)
make seed-legacy NS=<ns> [SCALE=demo|full] [TARGETS=postgres,dynamodb,s3]
make seed-legacy-validate NS=<ns>      # re-derives counts/checksums vs testdata/legacy/manifests/<ns>.json
```

- demo scale seeds in ~30s (2k docs, 10k dynamo items, 3 days of hourly s3 events).
- Manifests are gitignored runtime artifacts; reruns are byte-identical per (ns, scale).
- NS must fullmatch `[A-Za-z0-9_]+`; DynamoDB rows use plain-UUID `id` + `ns` attribute
  (clears are ns-scoped scans, safe for the shared table).
- Cleanup: drop schema `otterworks_<ns>`, delete dynamo items where ns=<ns>,
  delete `s3://otterworks-data-lake/events/<ns>/`, remove the manifest.
- Gotcha: `uv run - <<EOF` stdin scripts don't read inline-deps headers — pass
  `--with psycopg2-binary --with boto3` when importing legacy_common ad hoc.
- Gotcha: `$(printf 'x\n')` strips the trailing newline — use `$'x\n'` when
  testing newline rejection.

## Reverting a Run

```bash
make testdata-clean NS=<ns>   # single command; drops the entire schema
```

This is safe and total — no partial state.
