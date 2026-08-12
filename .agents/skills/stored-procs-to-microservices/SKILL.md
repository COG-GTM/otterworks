---
name: stored-procs-to-microservices
description: Applies when extracting business logic out of the legacy billing stored procedures into the billing service and proving parity in this repository.
---

# Stored procedures to billing service

## Repository map

- Legacy procedures: `services/legacy-billing/db/procs/{plans,rating,invoicing,dunning}.sql`.
- Thin legacy HTTP layer: `services/legacy-billing/app/` (Flask/Jinja).
- Scenarios: `procs/scenarios/<module>/*.yaml`.
- Immutable transcripts: `procs/transcripts/<module>/*.json`; global index
  `procs/transcripts/index.json`; procedure and fixture fingerprints
  `procs/transcripts/SOURCE_SHA` and `procs/transcripts/FIXTURE_SHA`.
- Declarative parity contract: `procs/routes.yaml`.
- Approved ledgers: `procs/rules/<module>.rules.yaml`.
- Replay and gate harness: `procs/harness/{record,replay,rules_gate,list}.py`.
- Reports generated locally at `procs/reports/parity.{md,json}` and published
  as CI artifacts; paste the parity summary and failure detail into the PR
  body rather than committing the generated files.
- Extracted target: `services/billing-service/` (`app/domain.py`,
  `app/repository.py`, `app/main.py`, `tests/`); target schema is `billing_svc`.
- Local client fixture: `frontend/client-app/src/features/billing/`;
  route registration is in `frontend/client-app/src/App.tsx`; Vite proxy is in
  `frontend/client-app/vite.config.ts`.

## Commands

Every stack command requires `NS=<namespace>`. The default verified namespace
uses ports 55445/8109/56445/12109.

```bash
make procs-up NS=dev
make procs-down NS=dev
make procs-list
make procs-record NS=dev
make procs-rules-gate MODULE=plans
make procs-rules-gate ALL=1
make procs-parity NS=dev
make procs-parity NS=dev MODULE=plans
make procs-parity NS=dev MODULE=plans SCENARIO=PLANS-001
```

`procs-up` builds and waits for healthy Compose services. `procs-list` prints
module status, scenario count, rule claims, and scenario mappings. A healthy
rules run prints `Rules gate PASS: plans`. A healthy full parity run prints
`Parity PASS=5 FAIL=0 SKIP=19` and writes both local report files, which CI
uploads as artifacts. Extracted modules
are graded; pending modules are `SKIP`, never `PASS`.

## Module contract and status

`procs/routes.yaml` marks a module extracted with `status: extracted` and maps
each entrypoint to its target method/path, input mapping, response fields, and
mutation probes. Pending modules have `status: pending` and no target
entrypoints.

| Module | Status | Scenarios | Entrypoints |
| --- | --- | ---: | --- |
| plans | extracted | 5 | `billing.fn_list_plans` (1), `billing.fn_entitlement` (2), `billing.sp_change_plan` (2) |
| rating | pending | 8 | `billing.fn_usage_rating` (6), `billing.fn_usage_summary` (1), `billing.sp_finalize_rating` (1) |
| invoicing | pending | 6 | `billing.fn_invoice_preview` (2), `billing.sp_issue_invoice` (3), `billing.fn_invoice_lines` (1) |
| dunning | pending | 5 | `billing.fn_overdue_accounts` (1), `billing.sp_schedule_dunning` (2), `billing.sp_suspend_overdue` (2) |

## Ledger and target tests

The plans ledger contains `PLANS-001` through `PLANS-004`. Target tests in
`services/billing-service/tests/test_domain.py` use
`@pytest.mark.rule("<id>")`. `make procs-rules-gate MODULE=plans` requires:

- valid ledger schema and required fields;
- every decision approved/non-pending with reviewer and date;
- explicit `answer` for every `question`;
- every rule claiming scenarios and every module scenario claimed;
- source ranges resolving to that module's own
  `services/legacy-billing/db/procs/<module>.sql`;
- every ledger rule covered by a target marker;
- every discovered marker belonging to a rule in an approved ledger.

`ALL=1` validates every ledger in `procs/rules/`. Gate exit codes are
`2` missing ledger, `3` invalid decision, `4` invalid scenario coverage,
`5` invalid source, `6` invalid marker coverage, and `7` invalid schema.

## Recording and immutability

Normal recording is refused when it would overwrite existing transcripts.
Procedure-source changes require:

```bash
make procs-record NS=dev ALLOW_RERECORD=1
```

If only recorder/harness behavior changed (for example normalization), use the
audited path:

```bash
make procs-record NS=dev ALLOW_RERECORD=1 RERECORD_REASON=harness-change
```

For a scenario/probe redesign with unchanged procedures, use:

```bash
make procs-record NS=dev ALLOW_RERECORD=1 RERECORD_REASON=scenario-redesign
```

The reason is written into regenerated transcripts. Each reason is legitimate
only for its named non-procedure change with unchanged procedures; neither is a
substitute for recording a changed procedure source. Partial recordings merge
`index.json` entries by module/scenario. Unknown modules fail and an empty
recording does not rewrite the index or fingerprint.

Recorder exit codes are `2` immutable transcript overwrite, `3` legacy stack
unreachable, and `4` scenario/unknown-module failure.

## Replay diagnostics and exit codes

Replay checks the global fingerprint and every selected transcript's own
`source_sha`, resets the target before grading, and once grading begins writes
`procs/reports/parity.{md,json}` on every exit path. Missing response paths,
null/scalar parents, and non-list row/collect values are graded failures rather
than traceback crashes. A target non-200 records a status failure without
attempting response-field comparison.

Replay exit codes are:

- `1`: one or more graded parity failures;
- `3`: target unreachable;
- `6`: contract missing, unmapped, or failed rules gate;
- `7`: procedure/transcript source mismatch;
- `8`: target reset refused or failed;
- `9`: module/scenario selection matched no transcripts.

Reset refusals identify `BILLING_SVC_ALLOW_INTERNAL_RESET` as the disposable
stack setting required by the harness.

## Namespace isolation

`NS` is hashed with `zlib.crc32(NS) % 1000`. Host ports are:

- legacy Postgres: `55432 + offset`;
- legacy app: `8096 + offset`;
- target Postgres: `56432 + offset`;
- target app: `12096 + offset`.

All Compose publications bind to `127.0.0.1`. The Make targets derive the same
ports for recorder and replay URLs. Separate namespace projects and volumes
can run concurrently without sharing host ports or databases.

## Client fixture boundary

The local Vite server proxies `/billing-api/*` to
`BILLING_SERVICE_URL` or the default target at `http://localhost:12109`.
Start it with:

```bash
cd frontend/client-app
npm run dev
```

`VITE_ENABLE_BILLING_FIXTURE` controls the billing routes. Dev enables them by
default. A preview build must opt in explicitly:

```bash
VITE_ENABLE_BILLING_FIXTURE=true npm run build
npm run start -- --host 127.0.0.1 --port 4173
```

The `/billing-api` proxy is used by the dev server and by that flagged preview.
Builds without the flag leave the routes unregistered. The billing screens are
local parity-fixture pages only: they are not deployed through the normal
client, Helm, or EKS paths.
The fixture deliberately has no authentication because the procedures have no
notion of a caller; a real extraction must add authentication and tenant
scoping at the edge.

## Clean run reversion

Stop and remove a disposable namespace with:

```bash
make procs-down NS=<namespace>
```

This runs Compose `down -v`, removing that namespace's containers, networks,
and volumes while leaving other namespaces untouched. Keep checked-in
transcripts, ledgers, and contracts unchanged unless an explicitly audited
recording was required; parity reports are generated locally and uploaded by
CI rather than committed. Restore any temporary source tweak before rerunning
parity.
