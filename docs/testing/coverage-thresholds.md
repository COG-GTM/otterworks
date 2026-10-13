# Coverage thresholds (ratchet)

CI enforces a minimum line/statement coverage per service. Each gate was set at or just below the
coverage measured on `main` when it was introduced, so it only fails on regressions.

| Service | Language | Where the gate lives | Measured | Minimum |
| --- | --- | --- | --- | --- |
| api-gateway | Go | `.github/workflows/ci.yml` (`scripts/ci/check-go-coverage.sh coverage.out 58`) | 59.2% statements | 58% |
| document-service | Python | `services/document-service/pyproject.toml` `[tool.coverage.report] fail_under` | 81% lines | 80% |
| search-service | Python | `services/search-service/.coveragerc` `fail_under` | 75.2% lines | 74% |
| collab-service | TypeScript | `services/collab-service/jest.config.js` `coverageThreshold.global` | 65.1% lines / 64.0% stmts / 49% funcs / 37.4% branches | 64 / 63 / 48 / 37 |

Not yet gated (no coverage report wired into CI today; add one, measure, then add a row):
auth-service and report-service (Java, JaCoCo), file-service (Rust, `cargo llvm-cov`),
notification-service (Kotlin, Kover), analytics-service (Scala, sbt-scoverage),
admin-service (Ruby, SimpleCov), audit-service (C#, coverlet), billing-service (Python, pytest-cov),
web-app / admin-dashboard (Jest).

## How to ratchet

1. Run the service's coverage command locally (same as CI):
   - Go: `cd services/api-gateway && go test -coverprofile=coverage.out ./... && go tool cover -func=coverage.out | tail -1`
   - Python: `cd services/<svc> && pytest --cov=app` (prints the total and the `fail_under` result)
   - TypeScript: `cd services/collab-service && npx jest --coverage --coverageReporters=text-summary`
2. Set the minimum to the new measured value rounded **down** to a whole percent (leave ~1 point of
   headroom for noise). Never lower a gate to make a PR pass; add tests instead, or record the reason
   in the PR description and get CODEOWNERS approval.
3. Update the table above in the same PR.

Good moments to ratchet: any PR that adds meaningful tests to a service, and a periodic sweep
(e.g. monthly) by the owning team.
