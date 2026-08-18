---
name: secure-refactor-equivalence
description: >
  Repo-specific mechanics for closing a source-level security finding in OtterWorks
  by refactoring the affected class and proving functional equivalence. Covers the
  registered findings and their subject classes, the Makefile targets that drive the
  record → grade → suite → runtime-probe loop, how the fixture is seeded, which
  behaviors are under contract, the runtime probes that must flip, and how to revert.
---

# Secure Refactor with Functional Equivalence — OtterWorks

Repo-specific mechanics behind the `!secure-refactor-equivalence` Playbook.
Auto-loaded when Devin works in this repository.

## The findings on `main`

`main` deliberately ships three source-level flaws in `document-service` — they
are the durable before-state this exercise starts from, and they are **not** to
be "fixed" outside a refactor branch.

| Finding | CWE | Subject | Class.methods | Runtime probe |
|---|---|---|---|---|
| `OW-SEC-401` | CWE-89 SQL injection | `app/services/document_query_repository.py` | `DocumentQueryRepository._where/count_documents/search_documents` | `DAST-SQLI-ERROR-BASED` |
| `OW-SEC-402` | CWE-22 path traversal | `app/services/export_archive.py` | `ExportArchive.read_export` | `DAST-PATH-TRAVERSAL-EXPORT` |
| `OW-SEC-403` | CWE-328 weak digest | `app/services/share_link.py` | `ShareLinkService.mint_token/verify_token` | `DAST-SHARE-TOKEN-FORGERY` |

`security/equivalence/findings.yaml` is the machine-readable source of truth
(subject paths, class and methods, the secure pattern expected, the linked probe).
A finding's `subject` is its own class only — changing it is what makes the
harness grade that finding as a refactor. The shared route module is listed under
`observes` instead, so editing `app/api/documents.py` while closing one finding
does not flip the other two into refactor grading.
`make eq-list` prints it together with the state of each finding's evidence.

Routes that reach them: `GET /api/v1/documents/` (filters `title`,
`content_type`, `sort`, `direction`), `GET /api/v1/documents/exports?name=`,
`GET /api/v1/documents/shared?document_id=&token=`. The exports and shared
routes are deliberately unauthenticated **in this service**: in the deployed
topology they sit behind `api-gateway`, which owns authentication and tenant
scoping at the edge. A real extraction of these handlers adds that boundary;
closing the three findings here does not, and must not widen the routes'
contract to compensate.

## Commands

```bash
make eq-list                        # findings, case counts, evidence state
make eq-gate                        # grade every finding for the state it is in
make eq-baseline                    # prove the recorded before-state still reproduces
make eq-verify                      # grade a refactor: contracts unchanged, attacks closed
make eq-exploit                     # do the attack cases still fire? (ignores the recording)
make eq-exploit-refactored          # closed exploit verdict required from every changed subject
make eq-tests                       # module suite vs. the recorded pass list
make eq-record REASON="..."         # record the before-state as reference evidence
```

All accept `FINDING=OW-SEC-401|OW-SEC-402|OW-SEC-403`. Exit codes: `0` pass,
`1` a real failure (a contract case diverged, an attack still fires, the suite
regressed, the interface drifted), `2` inconclusive — missing or stale evidence,
an unmeasured case, a subject graded at the wrong stage. `3` no verdict reached.
`2` and `3` are never a pass.

`eq-gate` picks the stage per finding from the fingerprints: a subject that still
matches the recording is graded as the before-state, a changed subject is graded
as a refactor. A run cannot choose the easier contract for itself. CI runs
`eq-gate`, `eq-exploit-refactored` and `eq-tests`
(`.github/workflows/equivalence-gate.yml`) and uploads
`security/equivalence/reports/*.json` as artifacts — those reports are
git-ignored generated output, so paste the summary lines into the PR instead of
committing them.

## How the harness works

- `security/equivalence/cases/OW-SEC-4xx.json` — the cases. `policy: contract`
  must be byte-identical after the refactor; `policy: attack` must stop firing.
  `kind` is `direct` (call the class), `http` (call the ASGI app) or `probe` (a
  named multi-step probe in the emitter).
- `security/equivalence/seed/document-service.json` — the **only** fixture setup:
  six documents across two owners (one deleted, one template), two files in the
  export archive and one file outside it. Every case must be reproducible from
  this seed alone.
- `security/equivalence/harness/emit_document_service.py` — builds the fixture
  (in-memory SQLite seeded through the ORM, a temp archive directory, the env the
  services read) and emits one observation per case. It never decides pass/fail.
- `security/equivalence/harness/equivalence_check.py` — records, fingerprints and
  grades. Detectors are a closed set (`text_matches`, `rows_contain_owner`,
  `json_field_true`) evaluated here, so "exploited" is judged by the same code
  before and after.
- `security/equivalence/expected/OW-SEC-4xx.json` — the recorded evidence, with
  the fingerprint of the subject sources, the seed, the cases and the emitter, the
  captured interface signatures, and the suite pass list. Committed, and **not**
  to be hand-edited: `record` refuses to overwrite without `ALLOW_RERECORD=1` and
  a `REASON`, and refuses entirely if an attack case does not reproduce. Be
  precise about what the control actually is: the fingerprints staleness-flag
  changes to the *inputs* (subject, seed, cases, emitter), a recorded case that
  disappears from the case file grades as `missing`, and a changed subject owes
  `eq-exploit-refactored` a closed verdict — but the evidence file itself is
  guarded by review of its committed diff plus the audited re-record path, not
  by a self-certifying hash. The `observed` files (`app/api/documents.py`) are
  fingerprinted as provenance only; a route-only divergence is caught by the
  contract comparison, not by staleness.

Two fixture facts worth knowing before you debug a red gate:

- SQLite has no `uuid` type, so the emitter binds uuids hyphenated the way
  PostgreSQL renders one. Without that, the raw SQL's text comparison never
  matches and every owner-scoped case silently degrades to an empty list.
- The fixture's temp directory leaks into a `FileNotFoundError` message, which is
  itself under contract, so the emitter redacts the fixture root to `<fixture>`
  at capture time. Keep observations deterministic rather than comparing loosely.

## Running it

```bash
cd services/document-service && poetry install --no-interaction   # once
cd /path/to/repo && make eq-list && make eq-gate && make eq-tests
```

The harness runs under `uv` and shells into the module with its own Poetry
environment, stripping `VIRTUAL_ENV`/`POETRY_ACTIVE` so the nested run does not
inherit the outer one. `JWT_SECRET` is dropped for the same reason the suite
drops it: a stale export changes the app's auth behavior.

Nine pre-existing failures in `tests/test_documents_api.py` (mutating endpoints
called without an auth header, asserting `200` against a `401`) are on `main` and
are **not** yours to fix — they are excluded because the gate compares against
the recorded pass list, not against "everything green".

## Runtime proof

```bash
make up                                                  # docker compose stack
make dast-verify FINDING=DAST-SQLI-ERROR-BASED DAST_TARGET=http://localhost:8080
make dast-scan DAST_TARGET=http://localhost:8080         # the whole suite
```

`security/dast/` is the existing probe suite — reuse it, do not write a new probe
for a finding it already covers. Rebuild the changed service before re-probing
(`docker compose up -d --build document-service`), or the probe re-tests the old
image and a "closed" verdict is meaningless. See
`.agents/skills/dast-remediation/SKILL.md` for the DAST loop in detail. Never
point a scan at `t-main.otterworks.app`.

If the full stack will not build in your environment (e.g. `auth-service`'s
Maven resolution is rate-limited), a loopback-bound shim that imports the
unchanged document-service app and adds only registration/login endpoints is
enough to exercise the document-service-owned probes — but every gateway-,
auth- or search-owned row in the DAST report is then **untested**, and must be
reported as untested, never as passing.

`DAST-PATH-TRAVERSAL-EXPORT` first reads the `dast-control.txt` export the
document-service image seeds into `EXPORT_ARCHIVE_DIR` and reports
`inconclusive` when that read fails: without an archive root on disk every
traversal dies on the missing directory and a vulnerable build is
indistinguishable from a fixed one. An `inconclusive` verdict there means the
target's archive is not wired up, not that the finding is closed.

## Scope and revert

- Work on your own branch (`workshop-<attendee_id>` for participants); the
  before-state stays on `main` so the exercise repeats.
- Revert a refactor with `git checkout main -- services/document-service/app/services`
  and re-run `make eq-baseline`, which must go green again.
- Do not touch `security/deps/` (a different exercise) or the planted
  admin-service Rails bug documented in `AGENTS.md`.
