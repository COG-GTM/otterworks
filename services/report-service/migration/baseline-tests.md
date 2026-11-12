# report-service — Java 8 test baseline

Recorded before the Java 8 → 21 migration (plan step `s1.1`). Later phases compare against this list: every test below must still exist and pass (or be explicitly accounted for) after the JUnit / Spring Boot / JDK upgrades.

## How it was run

| | |
|---|---|
| Source tree | `main` @ `cc23bf19` |
| JDK | Eclipse Temurin `1.8.0_512-b09` (same distribution/major as the `report-service` job in `.github/workflows/ci.yml`) |
| Maven | Apache Maven 3.9.9 |
| Command | `mvn -B test` (from `services/report-service`) |
| Framework | Spring Boot 2.5.15, JUnit 4.13.2 (Jupiter excluded from `spring-boot-starter-test`), maven-surefire-plugin 2.22.2 |
| Result | `Tests run: 50, Failures: 0, Errors: 0, Skipped: 1` — **BUILD SUCCESS** |

Cross-check: the same command on Ubuntu OpenJDK `1.8.0_504` gives the identical result (50 run, 0 failures, 0 errors, 1 skipped).

## Per-class outcome

| Test class | Run | Passed | Failed | Errors | Skipped |
|---|---:|---:|---:|---:|---:|
| `com.otterworks.report.ReportServiceTest` | 8 | 8 | 0 | 0 | 0 |
| `com.otterworks.report.controller.ReportControllerIntegrationTest` | 16 | 16 | 0 | 0 | 0 |
| `com.otterworks.report.deps.DependencyTranscriptEmitterTest` | 1 | 0 | 0 | 0 | 1 |
| `com.otterworks.report.service.CsvReportGeneratorTest` | 6 | 6 | 0 | 0 | 0 |
| `com.otterworks.report.service.ExcelReportGeneratorTest` | 9 | 9 | 0 | 0 | 0 |
| `com.otterworks.report.service.PdfReportGeneratorTest` | 5 | 5 | 0 | 0 | 0 |
| `com.otterworks.report.service.ReportHeaderRendererTest` | 5 | 5 | 0 | 0 | 0 |
| **Total** | **50** | **49** | **0** | **0** | **1** |

### Skipped test

- `DependencyTranscriptEmitterTest#emitTranscript` — skips itself via `Assume.assumeTrue` unless `-Dow.deps.cases` and `-Dow.deps.observed` are set. It is driven only by the dependency harness (`security/deps`), never by a plain `mvn test`, so the skip is expected. Under the harness it runs and passes (see below).

## Pass list (class#method)

One line per test method, sorted. `SKIPPED` marks the single expected skip; every other line passed on JDK 8.

```text
com.otterworks.report.ReportServiceTest#createCsvReportShouldReturnAccepted  PASS
com.otterworks.report.ReportServiceTest#createExcelReportShouldReturnAccepted  PASS
com.otterworks.report.ReportServiceTest#createReportShouldReturnAccepted  PASS
com.otterworks.report.ReportServiceTest#createReportWithoutNameShouldReturn400  PASS
com.otterworks.report.ReportServiceTest#downloadNonExistentReportShouldReturn404  PASS
com.otterworks.report.ReportServiceTest#getReportNotFoundShouldReturn404  PASS
com.otterworks.report.ReportServiceTest#healthEndpointShouldReturnOk  PASS
com.otterworks.report.ReportServiceTest#listReportsShouldReturnEmptyList  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#createCsvReportReturns202  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#createExcelReportReturns202  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#createPdfReportReturns202WithCorrectBody  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#createReportWithoutCategoryReturns400  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#createReportWithoutNameReturns400  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#createReportWithoutTypeReturns400  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#deleteExistingReportReturns204  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#deleteNonExistentReportReturns404  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#downloadNonExistentReportReturns404  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#downloadPendingReportReturns409  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#getNonExistentReportReturns404  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#getReportByIdReturnsCreatedReport  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#healthEndpointReturnsServiceMetadata  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#listReportsByStatusReturnsArray  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#listReportsByUserIdReturnsArray  PASS
com.otterworks.report.controller.ReportControllerIntegrationTest#listReportsForUnknownUserReturnsEmptyArray  PASS
com.otterworks.report.deps.DependencyTranscriptEmitterTest#emitTranscript  SKIPPED
com.otterworks.report.service.CsvReportGeneratorTest#generateCsvProducesNonEmptyFile  PASS
com.otterworks.report.service.CsvReportGeneratorTest#generateCsvWithEmptyDataProducesEmptyFile  PASS
com.otterworks.report.service.CsvReportGeneratorTest#generatedCsvContainsCorrectColumnHeaders  PASS
com.otterworks.report.service.CsvReportGeneratorTest#generatedCsvContainsCorrectNumberOfDataRows  PASS
com.otterworks.report.service.CsvReportGeneratorTest#generatedCsvContainsMetadataComments  PASS
com.otterworks.report.service.CsvReportGeneratorTest#generatedCsvFileNameContainsReportName  PASS
com.otterworks.report.service.ExcelReportGeneratorTest#dataSheetCellsContainExpectedValues  PASS
com.otterworks.report.service.ExcelReportGeneratorTest#dataSheetContainsCorrectHeaders  PASS
com.otterworks.report.service.ExcelReportGeneratorTest#dataSheetContainsCorrectNumberOfRows  PASS
com.otterworks.report.service.ExcelReportGeneratorTest#generateExcelProducesNonEmptyFile  PASS
com.otterworks.report.service.ExcelReportGeneratorTest#generateExcelWithEmptyDataProducesValidFile  PASS
com.otterworks.report.service.ExcelReportGeneratorTest#generatedExcelFileNameContainsReportName  PASS
com.otterworks.report.service.ExcelReportGeneratorTest#generatedExcelHasSummaryAndDataSheets  PASS
com.otterworks.report.service.ExcelReportGeneratorTest#generatedExcelIsReadableByPoi  PASS
com.otterworks.report.service.ExcelReportGeneratorTest#summarySheetContainsReportMetadata  PASS
com.otterworks.report.service.PdfReportGeneratorTest#generatePdfFileNameContainsReportName  PASS
com.otterworks.report.service.PdfReportGeneratorTest#generatePdfProducesNonEmptyFile  PASS
com.otterworks.report.service.PdfReportGeneratorTest#generatePdfWithEmptyDataProducesValidPdf  PASS
com.otterworks.report.service.PdfReportGeneratorTest#generatePdfWithMultipleRowsProducesLargerFile  PASS
com.otterworks.report.service.PdfReportGeneratorTest#generatedPdfStartsWithPdfHeader  PASS
com.otterworks.report.service.ReportHeaderRendererTest#rendersPeriodFromTwoVariables  PASS
com.otterworks.report.service.ReportHeaderRendererTest#rendersReportVariables  PASS
com.otterworks.report.service.ReportHeaderRendererTest#rendersRowCount  PASS
com.otterworks.report.service.ReportHeaderRendererTest#reportNameContainingATokenIsInsertedLiterally  PASS
com.otterworks.report.service.ReportHeaderRendererTest#undefinedVariableFailsInsteadOfLeakingPlaceholder  PASS
```

## Dependency-remediation harness baseline

`make deps-transcript-baseline MODULE=report-service` replays `security/deps/cases/report-service.json`. The harness pins this module to JDK 11 (`security/deps/modules.yaml`) because the `attack-script-lookup` case needs Nashorn (removed in JDK 15); it resolved to `/usr/lib/jvm/java-11-openjdk-amd64` (OpenJDK 11.0.32).

```text
transcript stage: baseline
| module         | status   |   cases | detail   |
|----------------|----------|---------|----------|
| report-service | pass     |      11 |          |

TRANSCRIPT PASSED: 11 cases across 1 modules.
```

Observed values (all 11 match the recorded before-state):

| Case | Policy | Observed |
|---|---|---|
| `banner-title` | contract | ok `# OtterWorks Report: Quarterly Usage` |
| `banner-period` | contract | ok `# Period: 2026-01-01 to 2026-03-31` |
| `banner-rows` | contract | ok `# Rows: 42` |
| `banner-undefined-variable-rejected` | contract | error `IllegalArgumentException` (Cannot resolve variable 'notProvided') |
| `footer-base64-and-const` | contract | ok `# Generated by OtterWorks Reporting \| INTERNAL USE ONLY` |
| `configured-sys-property` | contract | ok `sep=/` |
| `configured-url-decoder` | contract | ok `report name` |
| `configured-file-lookup` | contract | ok `banner-from-file` |
| `attack-script-lookup` | attack | ok `7` (lookup still resolves — pre-remediation state) |
| `attack-dns-lookup` | attack | ok `127.0.0.1` (lookup still resolves — pre-remediation state) |
| `attack-url-lookup` | attack | error `IllegalArgumentException` |

Note for later phases: the `script` lookup only resolves because JDK 11 still ships Nashorn. On JDK 21 that case cannot be measured as-is, so the harness must keep running it on JDK 11 (or the case must be re-recorded) once the service moves to Java 21.

## Reproduce

```bash
cd services/report-service
JAVA_HOME=<temurin-8> PATH=$JAVA_HOME/bin:$PATH mvn -B test
cd ../.. && make deps-transcript-baseline MODULE=report-service
```
