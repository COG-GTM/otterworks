# Playbook: Extract business logic out of stored procedures into a service, and prove it

> **Facilitator / author:** this file is the source for a **Devin Playbook**.
> Copy its contents into your Devin organization (Settings → Playbooks → *Create
> a new Playbook*) so sessions can invoke it as `!stored-procs-to-microservices`.
> See [Creating Playbooks](https://docs.devin.ai/product-guides/creating-playbooks).

## Overview

Use this playbook when an application's business logic lives **inside the
database** — stored procedures, functions, packages, triggers — and it has to
move out: into a service that owns the rules in ordinary code, usually behind a
modern UI. One module at a time, with a human approving the rules before any of
them are implemented, and a replay harness proving the new code reproduces the
old behavior.

The guiding principle: **the running legacy database is the source of truth, and
a rule does not exist until a human has approved it.** Not the schema comments,
not the wiki, not a plausible reading of the SQL. Two gates enforce that, and
neither is optional:

1. a **rule ledger** a human reviews and approves, so the ambiguities in decades
   of accreted SQL get decided by someone accountable rather than guessed at;
2. a **golden-transcript parity run** against the extracted service, so the
   approved rules are proven to be implemented, not merely described.

This is the part teams get wrong when they rewrite database logic. Reading a
1,200-line procedure and writing "clean" code that looks equivalent is easy; the
money is in the rounding direction, the inclusive date boundary, the credit
applied before the cap rather than after. Those never appear in documentation
and each one is a billing incident. So: derive the rules, get them approved,
implement, then replay recorded legacy behavior and let it fail you.

## Required from user

- **The legacy database** — the procedures/functions and a way to run them, with
  deterministic seed data. If you cannot execute the legacy logic, stop: you have
  no source of truth and nothing to record.
- **The module to extract** — one bounded context (a set of procedures that own
  their tables), not the whole database. If the user names the whole thing, pick
  the smallest module with real rules and propose the fan-out for the rest.
- **The reviewer** — who approves the rule ledger. This is the human in the loop;
  the gate will not pass without their decision, and you must not approve on
  their behalf.
- **The target** — the service that will own the logic and, where relevant, the
  UI that will consume it. Follow whatever the repo already does; a new
  convention is a cost, not a contribution.

## Procedure

1. **Orient over the estate before touching anything.** Inventory the procedures,
   which tables each one writes, which are called from the application versus
   from other procedures, and where the module boundaries actually fall (shared
   tables and cross-procedure calls are the seams that will hurt). Report the map
   and confirm the module scope before proceeding.
2. **Record the legacy behavior first.** Drive the *running* legacy procedures
   through the scenario suite and record the results as immutable transcripts:
   the values returned and the state left behind. Do this before you write a
   line of the port, so the baseline cannot be influenced by your
   implementation. If a scenario cannot be recorded, fix the scenario — never
   the procedure.
3. **Derive the rules and write the ledger.** Read the procedures and write one
   entry per behavior: the rule, the source file and line range it comes from,
   the scenarios that exercise it, your confidence, and — this is the important
   part — an explicit **question** wherever the SQL is ambiguous or surprising.
   Ambiguity is the deliverable here: a rule you are unsure of, flagged, is worth
   more than a confident guess. Do not fill in the decision fields yourself.
4. **Stop at the human gate.** Hand the ledger to the reviewer and ask for
   decisions: approved, or changed-with-a-reason, plus answers to every question.
   Wait. Then implement **only** what was approved, and if a decision changes a
   rule, say so plainly — the transcripts record the legacy behavior, so an
   intentional change will show up as a parity failure and must be recorded as
   an accepted exception rather than quietly reconciled.
5. **Implement the module with the logic in code, not in SQL.** Reads and writes
   go through a thin data layer with no conditional or ordering logic in the
   queries; the rules live in plain, unit-testable functions. If you find
   yourself writing a `CASE` or an `ORDER BY` that encodes a rule, you have moved
   the logic sideways instead of out. Tag each test with the rule id it proves,
   so the ledger and the tests cannot drift.
6. **Run the parity harness and let it fail.** Replay every recorded transcript
   against the new service and read the failures as findings, not as noise. Each
   one is the legacy telling you a rule you got wrong. Fix the code against the
   procedures — never edit a transcript, a scenario, or the mapping contract to
   make a red run go green. Iterate to a clean run, then run the module's tests,
   linters, and build.
7. **Wire the UI to the service, not the database.** Where the module had screens,
   point them at the new service. Verify with the app running, not by reading the
   code. The parity fixture deliberately has no authentication because the
   procedures have no notion of a caller; a real extraction must add
   authentication and tenant scoping at the edge.
8. **Open a PR per module** with the ledger, the mapping notes, and the parity
   evidence in it, and let the automated review pass over it. The parity report
   is generated locally and published as a CI artifact; paste its `PASS/FAIL/SKIP`
   summary line and any failure detail into the PR body alongside the ledger.
   A PR that says "extracted, tests pass" without a green parity run against
   recorded legacy behavior has proven nothing.
9. **Fan out the remaining modules in parallel.** One child session per module,
   each in its own namespace on its own branch, each running this same procedure
   to its own green parity run and its own PR. Monitor them; a child that reports
   "parity green" on a module still marked pending in the contract has skipped,
   not passed — check the report, not the summary.

## Specifications (postconditions)

- Every rule in the ledger has a human decision with a reviewer and a date, and
  every question raised has an explicit answer.
- Every scenario of the module is claimed by at least one rule, every rule cites
  a real line range in that module's own source, and every rule id appears on at
  least one test.
- The parity run is green for the extracted module and reports the untouched
  modules as skipped — never as passing.
- The transcripts are unchanged by the extraction, and the legacy procedures are
  unchanged by the extraction. `git diff` proves both.
- The business rules live in code with unit tests that do not need a database;
  the data layer holds no rule logic.
- Concurrent runs do not collide: each run has its own namespace/branch and its
  own data.
- The PR contains the ledger, the parity summary and failure detail, and the
  list of any accepted intentional behavior changes; CI retains the full
  generated report as an artifact.

## Worked example

From the validation run of this playbook on a PL/pgSQL billing estate.

The plan-catalog procedure ended with an unremarkable `ORDER BY`, and the
extracted service returned the same three plans with the same three prices. The
unit tests passed. Parity did not:

```text
Parity PASS=4 FAIL=1 SKIP=19
FAIL plans/PLANS-001
field codes:
  expected ['STARTER', 'GROWTH', 'SCALE']
  actual   ['SCALE', 'GROWTH', 'STARTER']
field fees:
  expected ['49.00', '149.00', '499.00']
  actual   ['499.00', '149.00', '49.00']
```

Same set, wrong order — and the order is the rule, because the first row of that
catalog is what the plan picker offers by default. Nothing in the procedure said
so; the ordering was a side effect of a clause a reader skims past, and it never
appeared in any documentation. Note also what the failure was *not*: no test was
red, and no reviewer looking at three correct plans and three correct prices
would have caught it. The recorded legacy behavior did.

Two things make that beat repeatable rather than lucky. The transcript was
recorded from the running procedures *before* the port existed, so it could not
agree with the port's mistakes. And the fix went into the domain code, against
the procedure — not into the transcript, which is exactly the shortcut that
would have turned this gate into decoration.

## Advice and pointers

- Record before you implement. A baseline captured after you have written the
  port is a baseline that agrees with your bugs.
- Treat every surprising line of SQL as a rule someone depends on. Legacy
  procedures accrete around real incidents; the weird branch is usually the
  business, not a mistake.
- The ambiguities are the value you add in step 3. A ledger of forty confident
  rules and no questions is a ledger nobody needed to review.
- Rounding, date boundaries, ordering, and the sequence in which credits/caps
  apply are where ports diverge. Give each its own scenario.
- Keep the module boundary honest: if extracting one module drags three others
  along, you picked the wrong module — say so instead of widening the change.
- Money and dates: use exact decimal types and the legacy rounding direction,
  and be explicit about inclusive versus exclusive day counts.
- Once the loop is green, put it on a schedule and on a trigger — the same
  procedure runs unattended (a nightly parity sweep against the legacy database,
  a run on every CI failure) so drift is caught by the harness rather than by a
  customer.

## Forbidden actions

- Do **not** modify the legacy procedures, the recorded transcripts, the
  scenarios, or the mapping contract to make parity pass. If parity is wrong, the
  port is wrong.
- Do **not** approve the rule ledger yourself, or record a decision on the
  reviewer's behalf. The gate is the human.
- Do **not** implement a rule that has no approved decision, and do not silently
  implement behavior the reviewer changed.
- Do **not** leave the logic in SQL — a rewritten query with the rule still in it
  is not an extraction.
- Do **not** extract more than the agreed module, and do not merge the extracted
  module into the durable before-state branch.
- Do **not** call a module done on unit tests alone. Green tests against your own
  understanding prove your understanding is self-consistent, nothing more.
