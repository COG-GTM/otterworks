# Legacy Billing — database-centric before state

`legacy-billing` is a deliberately database-centric billing application. It
is the durable before-state for the stored-procedure extraction flow: the
running application has server-rendered pages and a small JSON API, while the
business behavior is implemented in PostgreSQL under the `billing` schema.

This component is part of the OtterWorks golden app as a durable before-state.
The extraction target and the modern client are separate components and are
not part of this service.

## Modules

| Module | Procedures/functions | Routes |
|---|---|---|
| Plans | `fn_list_plans`, `fn_entitlement`, `sp_change_plan` | `/plans`, `/plans/<tenant>/entitlement`, `/plans/<tenant>/change` |
| Rating | `fn_usage_rating`, `fn_usage_summary`, `sp_finalize_rating` | `/api/rating/preview`, `/api/rating/finalize` |
| Invoicing | `fn_invoice_preview`, `fn_invoice_lines`, `sp_issue_invoice` | `/api/invoices/<tenant>/preview`, `/api/invoices/<tenant>/issue`, `/api/invoices/<invoice>/lines` |
| Dunning | `fn_overdue_accounts`, `sp_schedule_dunning`, `sp_suspend_overdue` | `/api/dunning/overdue`, `/api/dunning/schedule`, `/api/dunning/suspend` |

The Flask layer intentionally binds request values, calls a database
entrypoint, and renders the returned values. It does not reproduce domain
decisions in Python.

## Why it is an extraction candidate

- The domain boundaries are already grouped into database procedure modules.
- The service has a narrow HTTP surface that maps to those entrypoints.
- PostgreSQL owns the state transitions and computed billing results.
- The database can be reset to a deterministic seed for repeatable recordings.

## Full verification loop

The extracted reference service is `services/billing-service/`. The
declarative contract and human-approved ledger live under `procs/`. From the
repository root:

```bash
make procs-up NS=dev
make procs-rules-gate MODULE=plans
make procs-parity NS=dev
make procs-down NS=dev
```

The parity report compares the target's returned fields and target-side state
probes with immutable recordings. Modules not yet extracted remain skipped.
The legacy procedure files and recordings remain the source of truth for the
before-state.

## Run locally

From the repository root:

```bash
make procs-up NS=dev
curl http://localhost:8096/health
make procs-down NS=dev
```

The Compose profile is intentionally separate from the Helm/EKS path. It
models the legacy application running with its own PostgreSQL database.

## Database layout

- `db/schema.sql` — tables and constraints
- `db/procs/` — database entrypoints
- `db/seed.sql` — deterministic starting state
