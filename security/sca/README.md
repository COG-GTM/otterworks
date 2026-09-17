# Software composition analysis

Dependency scanning for every ecosystem in the repo. A service whose dependencies
nobody measures is not clean, it is unmeasured — so this directory registers every
dependency manifest in the tree, names the scanner that measures it, and makes an
unregistered manifest an inconclusive verdict rather than a silent gap.

```
security/sca/
├── projects.yaml           every dependency manifest, its scanner, and the explicit exemptions
├── baseline.yaml           the advisories accepted when coverage was wired (anything new fails)
├── harness/sca_scan.py     scanner drivers, OSV lookups, baseline grading
└── reports/                generated sca-report.json / .md (gitignored)
```

## Scanners

| Ecosystem | Projects | Scanner | Private tests |
|---|---|---|---|
| Go | `services/api-gateway` | `govulncheck` (reachability-aware) | none |
| Rust | `services/file-service` | `cargo-audit` against RustSec | none |
| Python | document, billing, search, `etl`, test harnesses | `pip-audit`, or OSV for pins that cannot be resolved offline | none |
| JVM | report, legacy-portal, auth, notification, analytics | the module's own build tool resolves the tree, OSV grades it | none |
| npm | collab, client-app (+ desktop), admin-dashboard, demo dashboard | `npm audit` | none |

## What is not scanned

Coverage is every ecosystem *registered* here, not every ecosystem in the tree. Two
are still unmeasured, recorded under `exempt:` in `projects.yaml` with the scanner
that would close them:

| Ecosystem | Components | Candidate scanner |
|---|---|---|
| Ruby (Bundler) | `services/admin-service` | `bundler-audit` |
| .NET (NuGet) | `services/audit-service`, `clients/windows-desktop` | `dotnet list package --vulnerable` |

They are exemptions rather than gaps in discovery: dropping a Gemfile or a `.csproj`
anywhere else in the tree still fails `make sca-list`.

Nothing here consumes a Snyk private test: Snyk's monthly quota is a shared budget,
and a composition scan that stops working when someone else exhausts it is not
continuous coverage. Snyk Code (SAST) still runs in the same workflow and degrades
to a warning when — and only when — the quota is the reason it could not run.

## The three commands

| Command | Question it answers | Fails when |
|---|---|---|
| `make sca-list` | Which manifests exist, which are registered, and which scanners does this machine have? | a manifest is neither registered nor exempt (exit 2) |
| `make sca-scan ECOSYSTEM=<go\|rust\|python\|jvm\|npm\|all>` | Is any advisory outside the baseline reachable? | a finding is not in the baseline (exit 1), a project could not be measured, or a manifest is unregistered (exit 2) |
| `make sca-baseline REASON="..."` | Record the last full scan as the accepted set | there is no full-run report, or a project in it is unmeasured (exit 2) |

Exit 1 is reserved for something the harness measured. Everything else — no scanner
on `PATH`, a build tool that cannot resolve, an unregistered manifest — exits 2, so a
run that inspected nothing never reads as a pass. A caller that branches on which
failure happened must not read `make`'s exit status (`make` reports 2 for any failed
recipe); get the invocation with `make -s sca-command` and run the subcommand through
it.

## Adding a service

Add it to `projects.yaml` under its ecosystem, run `make sca-scan ECOSYSTEM=<eco>`,
and fix what it reports. A manifest that genuinely has no server-side dependency
estate goes under `exempt:` with the reason — the gate demands a decision either way.
