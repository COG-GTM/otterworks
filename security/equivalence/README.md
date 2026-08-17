# Functional-equivalence gate for source-level security fixes

Some security findings cannot be closed by a version bump: the flaw is in this
repository's own code, and closing it means rewriting a class. The risk then is
not the security pattern but everything else the class does — ordering,
pagination, filter semantics, the error type a caller catches, the exact bytes a
consumer parses.

This harness is the control for that risk. It records what the affected class
observably does **before** the refactor, and afterwards proves two things at once:

- **contract cases** are byte-identical (functional equivalence), and
- **attack cases** no longer fire (the vulnerability is closed).

A refactor that changes a contract case is a regression even if the vulnerability
is gone. A refactor that leaves an attack case firing is not a fix.

## Layout

```
findings.yaml                    registered findings: subject, class, methods, secure pattern, probe
seed/document-service.json       the only fixture setup: documents, archive files, env
cases/OW-SEC-4xx.json            the cases, each labelled policy: contract | attack
expected/OW-SEC-4xx.json         recorded evidence + fingerprints + interface + suite pass list
harness/emit_document_service.py builds the fixture and emits observations (no verdicts)
harness/equivalence_check.py     records, fingerprints, grades, writes reports
reports/                         generated diagnostics (git-ignored, uploaded by CI)
```

## Commands

```bash
make eq-list                 # findings, case counts, evidence state
make eq-gate                 # grade each finding for the state it is actually in
make eq-baseline             # the recorded before-state must still reproduce
make eq-verify               # a refactor: contracts unchanged, attacks neutralised
make eq-exploit              # do the attacks still fire? (ignores the recording)
make eq-tests                # module suite vs. the recorded pass list
make eq-record REASON="..."  # record the before-state as reference evidence
```

`FINDING=<id>` narrows any of them. Exit codes: `0` pass, `1` a real failure,
`2` inconclusive (missing or stale evidence, an unmeasured case, the wrong
stage), `3` no verdict reached. `2` and `3` are never a pass.

## How it fails closed

- Evidence is fingerprinted over the **subject sources, the seed, the cases and
  the emitter**. Change any of them and the recording is stale, which is
  inconclusive — not a pass.
- `record` refuses to overwrite existing evidence without an explicit
  `ALLOW_RERECORD=1` and a `REASON`, which is stored in the recording alongside
  the previous fingerprint. Re-recording to get green leaves an audit trail.
- `record` refuses outright if an attack case does not reproduce: you cannot
  record a fixed tree as the before-state.
- `grade --stage baseline` refuses if the subject changed; `--stage remediated`
  refuses if it did not. `--stage auto` (what CI runs) decides per finding from
  the fingerprints, so a run cannot pick the easier contract for itself.
- Attack verdicts come from a **closed set of detectors** evaluated by the
  grader, never by the emitter — the same code judges "exploited" before and
  after.
- Contract observations are compared as whole structures with list order
  preserved. Ordering is a business rule here (newest first, caller-chosen sort),
  so neither side is canonicalised.
- Interface signatures are captured with the evidence, so a refactor that renames
  a parameter or changes a default fails as interface drift.
- The suite is compared against the pass list recorded with the evidence: a test
  that used to pass cannot be deleted on the way to green, and a test that
  vanishes is inconclusive.
- Every path writes a report to `reports/`, failures included.

See `.agents/skills/secure-refactor-equivalence/SKILL.md` for the repo mechanics
and `.workshop/playbooks/secure-refactor-equivalence.devin.md` for the portable
procedure.
