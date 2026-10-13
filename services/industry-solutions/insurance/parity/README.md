# Commission Pay parity harness

Mirrors `procs/` (billing): scenarios → Oracle transcripts → replay against the service → diff.

```
scenarios/<module>/NNN.yaml   one call (plus optional setup calls and state probes)
transcripts/<module>/*.json   what Oracle Free returned — committed, immutable
routes.yaml                   PL/SQL entrypoint → HTTP endpoint, probe SQL ↔ probe GET
rules/<module>.rules.yaml     rule ledger: statement, PL/SQL lines, scenarios, decision
harness/record.py             re-seeds the frozen fixture, runs PL/SQL via python-oracledb
harness/replay.py             resets the parity tenant, replays over HTTP, writes reports/parity.{md,json}
```

Each transcript stores `source_sha`, `fixture_sha` and `scenario_sha` (a hash of the scenario's
id, module, entrypoint, actor, inputs, setup and probes). `verify.py` and `replay.py` fail any
transcript whose fingerprints no longer match, so an edited scenario must be re-recorded.

```text
harness/rules_gate.py         every scenario claimed, every rule sourced + unit-tested
harness/verify.py             one fresh transcript per scenario (fingerprints match)
```

Comparison is on business fields only: outcome status, ORA code, the message for
`RAISE_APPLICATION_ERROR` codes (-20000..-20999), returned fields, and probe rows
(rates, splits, ledger, audit, facts, summary). Numbers are compared in canonical decimal
form. A scenario may declare a `divergence` naming a `divergence-accepted` ledger rule and
the expected target result; it is then reported `DIVERGED-APPROVED` instead of `PASS`.

CI (`.github/workflows/insurance-parity.yml`) replays the committed transcripts — the
Oracle Free image is not started in CI. Recording against Oracle is a local step
(`make insurance-up NS=dev && make commission-record NS=dev`).

Rule decisions are recorded by the extraction (`reviewer: workstream-h-extraction`,
status `extracted` / `divergence-accepted`); business-owner sign-off is still required
before cutover.
