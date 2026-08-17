# Dependency CVE remediation harness

A CVE against a third-party JAR is not fixed by editing one version string. It is
fixed when **no module can still reach the vulnerable version**, and when the
services that call that library **behave the same afterwards** — except for the
capability the advisory says must go away. This directory turns both of those
claims into commands that pass or fail.

```
security/deps/
├── advisory.yaml           the advisory under remediation: artifact, vulnerable range, candidate fixes
├── modules.yaml            every JVM module the gate measures, plus explicit exemptions
├── cases/<module>.json     behaviour cases per module, each tagged policy=contract|attack
├── expected/<module>.json  recorded transcripts (the evidence the gate compares against)
├── harness/deps_check.py   inventory + advisory gate + suite runner + transcript grading
└── reports/                generated inventory/gate/tests/transcript JSON (gitignored)
```

## The four commands

| Command | Question it answers | Fails when |
|---|---|---|
| `make deps-inventory` | Which module pulls the artifact, at which version, directly or through which parent, and where is the version declared? | a module's tree cannot be resolved (exit 2) |
| `make deps-gate` | Can the vulnerable version still be reached from any module? | any tree contains a version in the advisory's range (exit 1), or a module is unmeasured (exit 2) |
| `make deps-tests` | Does every affected module still build and pass its own suite? | any module's suite fails (exit 1) |
| `make deps-transcript` | Did the libraries' observable behaviour change where it must not, and stop where it must? | a contract case changed, or an attack case still resolves (exit 1) |

Run `make deps-inventory` and `make deps-tests` **before** touching a version, so
the "after" numbers have something to be compared against.

## Contract cases vs attack cases

Each case in `cases/<module>.json` carries a `policy`:

- **`contract`** — the value must be byte-identical to the recording. These are the
  business behaviours the remediation is not allowed to disturb: rendered report
  banners, notification bodies, portal branding, the strict rejection of an
  undefined variable.
- **`attack`** — the lookup the advisory is about. After remediation it must stop
  resolving, and the template text named by `attack_marker` must survive
  literally in the output. A remediation that leaves the exploit working fails
  here even if the version string changed.

`--stage baseline` grades every case, attack cases included, against the
recording: that is how the before-state proves it still reproduces.
`--stage remediated` applies the policies above. CI picks the stage from the
advisory gate's own verdict, so neither contract can be skipped.

Cases are self-contained: a case that needs a file on disk carries its
`fixture_content` and the harness materialises it, so a recording never depends
on setup the replay does not reproduce.

## Recording is audited

`expected/<module>.json` stores a SHA-256 of the case file it was recorded from.
Edit the cases and every gate reports `stale` and exits 2 — it will not silently
grade against a recording that no longer matches. Re-recording requires a reason
and an explicit override:

```bash
make deps-record REASON="baseline on commons-text 1.9" # first recording
make deps-record REASON="<why the old recording was wrong>" ALLOW_RERECORD=1
```

A red gate is either a real divergence or a defective fixture. Both are fixed at
the root; neither is fixed by re-recording the evidence.

## Adding a module

Register it in `modules.yaml`. Discovery cross-checks the registry against the
`pom.xml` / `build.gradle{,.kts}` files on disk: a JVM build file that is neither
registered nor listed under `exempt` (with a reason) fails every command, so the
blast radius cannot quietly become partial. To give a module behaviour cases, add
`cases/<module>.json` and a `DependencyTranscriptEmitterTest` in its own test
sources — the emitter records outcomes and the harness grades them, so one
comparator governs Java, Kotlin, Maven and Gradle alike.

## Reports

`reports/` is git-ignored: generated output churns the diff. Collect it as a CI
artifact (the workflow does) and paste the summary lines — the inventory table,
the suite counts, the gate verdict — into the PR body as the evidence.
