# report-service — Java 8 migration baseline

Before-state for the Java 17 / Spring Boot 3.2 / JUnit 5 / jakarta.* migration. Every later
step must keep these suites green with the same counts (or explain the delta).

Recorded 2026-09-29 against `main` @ `cc23bf1993db9db1c40dc7a4b475082443f80092`.

## Stack under test

| Item | Version |
|---|---|
| Java source/target | 1.8 |
| Spring Boot parent | 2.5.15 |
| Test framework | JUnit 4 (via `spring-boot-starter-test`), `org.junit.Assume` for skips |
| Surefire / compiler / jar plugins | 2.22.2 / 3.8.1 / 3.2.2 |

## Local run

Toolchain: Temurin `1.8.0_504-b01`, Apache Maven 3.6.3, Ubuntu 22.04 x86_64.

```bash
cd services/report-service
JAVA_HOME=<temurin-8> mvn -B test      # BUILD SUCCESS
JAVA_HOME=<temurin-8> mvn -B package   # BUILD SUCCESS -> target/report-service.jar (~77 MB)
```

| Test class | Run | Failures | Errors | Skipped |
|---|---:|---:|---:|---:|
| `com.otterworks.report.ReportServiceTest` | 8 | 0 | 0 | 0 |
| `com.otterworks.report.controller.ReportControllerIntegrationTest` | 16 | 0 | 0 | 0 |
| `com.otterworks.report.service.CsvReportGeneratorTest` | 6 | 0 | 0 | 0 |
| `com.otterworks.report.service.ExcelReportGeneratorTest` | 9 | 0 | 0 | 0 |
| `com.otterworks.report.service.PdfReportGeneratorTest` | 5 | 0 | 0 | 0 |
| `com.otterworks.report.service.ReportHeaderRendererTest` | 5 | 0 | 0 | 0 |
| `com.otterworks.report.deps.DependencyTranscriptEmitterTest` | 1 | 0 | 0 | 1 |
| **Total** | **50** | **0** | **0** | **1** |

`mvn -B package` runs the same 50 tests (1 skipped) before building the jar.

Skipped: `DependencyTranscriptEmitterTest.emitTranscript` — skips itself via
`assumeTrue("dependency transcript not requested", ...)` unless the deps harness passes
`-Dow.deps.cases=<file> -Dow.deps.observed=<file>`. That skip is expected in a plain run.

Expected noise, not failures: `ReportGenerationWorker` / `ReportDataFetcher` log `ERROR`
lines for `UnknownHostException` (analytics-, audit-, auth-service are not running in unit
tests), and H2 logs "Database is already closed" on JVM shutdown.

Deps harness (ambient JDK 11, same as `deps-remediation.yml`):

```
make deps-tests MODULE=report-service                 # pass — Tests run: 50, Failures: 0, Errors: 0, Skipped: 1
make deps-transcript-baseline MODULE=report-service   # pass — 11 cases
```

## CI on `main`

| Workflow → job | JDK | Latest run on `main` that executed the job | Result |
|---|---|---|---|
| `ci.yml` → `report-service` (compile, test, package) | Temurin 8.0.502-7 | [run 32431159330](https://github.com/COG-GTM/otterworks/actions/runs/32431159330/job/96622827218) @ `b41a5cd` | green — 50 run, 0 fail, 1 skipped |
| `deps-remediation.yml` → `deps` | Temurin 11.0.32 (+17 for Gradle modules) | [run 32431159349](https://github.com/COG-GTM/otterworks/actions/runs/32431159349/job/96622806463) @ `b41a5cd` | green — tests 50/0/1, gate reports commons-text 1.9 (expected before-state), baseline transcript 11/11 |
| `docker-build.yml` → `report-service-tests` | Temurin 8 | [run 30319342309](https://github.com/COG-GTM/otterworks/actions/runs/30319342309/job/90151738038) @ `98b28ad` | job green (44 run, 0 fail) — **stale, see below** |

Later `main` pushes (up to `cc23bf1`) skip `ci.yml` → `report-service` through its path
filter; `services/report-service/**`, `security/deps/**`, `Makefile` and both workflow files
are unchanged between `b41a5cd` and `cc23bf1`, so those runs still reflect current `main`.

### Pre-existing issues (not fixed here)

- `docker-build.yml` is now `workflow_dispatch`-only (release builds that push images) and
  has not run since 2026-07-28. Its last `report-service-tests` job predates
  `ReportHeaderRendererTest` and `DependencyTranscriptEmitterTest` (44 tests / 5 classes),
  so it has no run against current `main`.
- That same run (and every `docker-build.yml` run on record) is red overall: the
  `build-and-push` matrix failed (AWS credentials could not be loaded) or was cancelled for all services. The report-service test
  job itself was green.
