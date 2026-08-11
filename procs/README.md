# Stored-procedure recording loop

The `procs/` directory contains the declarative scenarios and immutable
recordings for the legacy billing application. The recordings are made against
the running PostgreSQL stack, not against a Python reimplementation.

## Loop

```bash
make procs-up NS=dev
make procs-list
make procs-record NS=dev
make procs-rules-gate MODULE=plans
make procs-parity NS=dev
cd frontend/client-app && npm run dev
make procs-down NS=dev
```

The Makefile derives the Postgres and HTTP host ports from `NS`, so separate
namespaces can run concurrently. Use `OUTPUT_DIR` when recording isolated
fixtures for a namespace-specific verification run.

The client Vite server proxies `/billing-api/*` to the extracted service. With
the default `NS=dev` stack, run the client command above and open
`http://localhost:3000/billing/plans`; no billing URL environment variable is
required. The billing routes are enabled by default in Vite dev/preview mode
and are controlled by `VITE_ENABLE_BILLING_FIXTURE`; production builds leave
them unregistered unless that flag is explicitly enabled. These screens are
part of this local parity fixture, not the deployed application. For another
namespace, set `BILLING_SERVICE_URL` to that namespace's derived target port
when starting Vite.

Each scenario resets the `billing` schema to the checked-in schema, procedure
definitions, and seed. The recorder invokes the declared entrypoint, captures
the selected result fields, runs the named state probes, and writes one JSON
transcript under `procs/transcripts/<module>/`.

Transcripts are immutable. Re-recording requires `--allow-rerecord` and a
changed procedure source hash. If only the harness changed, use the explicit
audited escape `--allow-rerecord --rerecord-reason harness-change`; each
resulting transcript records that reason. The namespace affects only the
running database; it is not written into transcript content.

Recording an existing checkout is intentionally refused unless the procedure
source changed. Through Make, the normal command is:

```bash
make procs-record NS=dev
```

For a procedure-source change, explicitly authorize the refresh:

```bash
make procs-record NS=dev ALLOW_RERECORD=1
```

For a harness-only normalization or recorder change, use the auditable reason:

```bash
make procs-record NS=dev ALLOW_RERECORD=1 RERECORD_REASON=harness-change
```

## Add a scenario

1. Add a YAML file under `procs/scenarios/<module>/`.
2. Set `id`, `module`, `description`, `entrypoint`, and `kind`.
3. Declare typed `inputs`.
4. Select returned `fields`, or use `capture_query` for a side-effecting
   procedure.
5. Add named `probes` with stable SQL queries.
6. Add stable `rules` identifiers for the later rules gate.
7. Run `make procs-record NS=<namespace>` against a fresh namespace and inspect
   the resulting transcript.

Scenario SQL should observe the legacy state. It should not duplicate
procedure logic in Python.

## Extraction verification

`routes.yaml` maps extracted legacy entrypoints to target HTTP endpoints. The
replay harness resets the target before each scenario, replays only modules
marked `extracted`, and records semantic field/probe comparisons in
`procs/reports/parity.md` and `parity.json`. Pending modules are reported as
`SKIP`, never as a pass. Replay also checks that the transcript source hash
still matches the checked-in procedure files.

The rules gate is a separate human-approval check:

```bash
make procs-rules-gate MODULE=plans
```

It validates the ledger decision, scenario coverage, source ranges, and
target-test markers before parity is allowed to grade an extracted module.
