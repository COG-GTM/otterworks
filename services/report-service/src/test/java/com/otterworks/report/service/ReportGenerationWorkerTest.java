package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportGenerationWorker}.
 *
 * Every collaborator (repository, data fetcher, the three file generators) is mocked, so the
 * test exercises the worker's orchestration — status transitions, category routing, row
 * capping and failure handling — without a Spring context, a database or real I/O beyond a
 * JUnit temporary folder.
 */
@RunWith(MockitoJUnitRunner.class)
public class ReportGenerationWorkerTest {

    private static final Long REPORT_ID = 42L;
    private static final Date CREATED_AT = new Date(1_704_067_200_000L); // 2024-01-01T00:00:00Z

    @Rule
    public TemporaryFolder tempFolder = new TemporaryFolder();

    @Mock
    private ReportRepository reportRepository;
    @Mock
    private ReportDataFetcher dataFetcher;
    @Mock
    private PdfReportGenerator pdfGenerator;
    @Mock
    private CsvReportGenerator csvGenerator;
    @Mock
    private ExcelReportGenerator excelGenerator;
    @Mock
    private AppConfig appConfig;

    private ReportGenerationWorker worker;

    @Before
    public void setUp() {
        worker = new ReportGenerationWorker(
                reportRepository, dataFetcher, pdfGenerator, csvGenerator, excelGenerator, appConfig);
    }

    @Test
    public void unknownReportIdIsIgnored() {
        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.empty());

        worker.generateReportAsync(REPORT_ID);

        verify(reportRepository, never()).save(any(Report.class));
        verifyNoInteractions(dataFetcher, pdfGenerator, csvGenerator, excelGenerator);
    }

    @Test
    public void completedCsvReportRecordsFileMetadata() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        File generated = fileContaining("id,name\n1,alpha\n");
        stubReport(report);
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
        when(dataFetcher.fetchAnalyticsData(report.getDateFrom(), report.getDateTo(), null))
                .thenReturn(rows(3));
        when(csvGenerator.generateCsv(eq(report), anyList(), eq("/tmp/reports"))).thenReturn(generated);
        // The worker mutates and re-saves the same instance, so the status has to be read at save time.
        List<ReportStatus> persistedStatuses = new ArrayList<>();
        when(reportRepository.save(any(Report.class))).thenAnswer(invocation -> {
            persistedStatuses.add(((Report) invocation.getArgument(0)).getStatus());
            return invocation.getArgument(0);
        });

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        assertEquals(generated.getAbsolutePath(), report.getFilePath());
        assertEquals(Long.valueOf(generated.length()), report.getFileSizeBytes());
        assertEquals(Integer.valueOf(3), report.getRowCount());
        assertNotNull(report.getCompletedAt());
        assertNull(report.getErrorMessage());

        assertEquals(Arrays.asList(ReportStatus.GENERATING, ReportStatus.COMPLETED), persistedStatuses);
        verify(reportRepository, times(2)).save(any(Report.class));
        verifyNoInteractions(pdfGenerator, excelGenerator);
    }

    @Test
    public void statusIsSetToGeneratingBeforeTheDataIsFetched() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        stubReport(report);
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
        when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), any()))
                .thenAnswer(invocation -> {
                    assertEquals(ReportStatus.GENERATING, report.getStatus());
                    return rows(1);
                });
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString()))
                .thenReturn(fileContaining("id\n1\n"));

        worker.generateReportAsync(REPORT_ID);

        verify(dataFetcher).fetchAnalyticsData(any(Date.class), any(Date.class), any());
        assertEquals(ReportStatus.COMPLETED, report.getStatus());
    }

    @Test
    public void pdfReportsAreRoutedToThePdfGenerator() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.PDF);
        stubReport(report);
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
        when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), any())).thenReturn(rows(1));
        when(pdfGenerator.generatePdf(eq(report), anyList(), anyString())).thenReturn(fileContaining("%PDF"));

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        verify(pdfGenerator).generatePdf(eq(report), anyList(), eq("/tmp/reports"));
        verifyNoInteractions(csvGenerator, excelGenerator);
    }

    @Test
    public void excelReportsAreRoutedToTheExcelGenerator() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.EXCEL);
        stubReport(report);
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
        when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), any())).thenReturn(rows(1));
        when(excelGenerator.generateExcel(eq(report), anyList(), anyString())).thenReturn(fileContaining("PK"));

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        verify(excelGenerator).generateExcel(eq(report), anyList(), eq("/tmp/reports"));
        verifyNoInteractions(csvGenerator, pdfGenerator);
    }

    @Test
    public void auditCategoriesFetchAuditData() throws Exception {
        for (ReportCategory category : new ReportCategory[]{ReportCategory.AUDIT_LOG, ReportCategory.COMPLIANCE}) {
            Report report = report(category, ReportType.CSV);
            stubReport(report);
            when(appConfig.getMaxRows()).thenReturn(50_000);
            when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
            when(dataFetcher.fetchAuditData(any(Date.class), any(Date.class), any())).thenReturn(rows(2));
            when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(fileContaining("x"));

            worker.generateReportAsync(REPORT_ID);

            assertEquals(ReportStatus.COMPLETED, report.getStatus());
            assertEquals(Integer.valueOf(2), report.getRowCount());
        }
        verify(dataFetcher, times(2)).fetchAuditData(any(Date.class), any(Date.class), any());
        verify(dataFetcher, never()).fetchAnalyticsData(any(Date.class), any(Date.class), any());
    }

    @Test
    public void userCategoriesFetchUserActivityData() throws Exception {
        for (ReportCategory category
                : new ReportCategory[]{ReportCategory.USER_ACTIVITY, ReportCategory.STORAGE_SUMMARY}) {
            Report report = report(category, ReportType.CSV);
            stubReport(report);
            when(appConfig.getMaxRows()).thenReturn(50_000);
            when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
            when(dataFetcher.fetchUserActivityData(any(Date.class), any(Date.class), any())).thenReturn(rows(4));
            when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(fileContaining("x"));

            worker.generateReportAsync(REPORT_ID);

            assertEquals(ReportStatus.COMPLETED, report.getStatus());
            assertEquals(Integer.valueOf(4), report.getRowCount());
        }
        verify(dataFetcher, times(2)).fetchUserActivityData(any(Date.class), any(Date.class), any());
    }

    @Test
    public void analyticsCategoriesFetchAnalyticsData() throws Exception {
        for (ReportCategory category
                : new ReportCategory[]{ReportCategory.COLLABORATION_METRICS, ReportCategory.SYSTEM_HEALTH}) {
            Report report = report(category, ReportType.CSV);
            stubReport(report);
            when(appConfig.getMaxRows()).thenReturn(50_000);
            when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
            when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), any())).thenReturn(rows(1));
            when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(fileContaining("x"));

            worker.generateReportAsync(REPORT_ID);

            assertEquals(ReportStatus.COMPLETED, report.getStatus());
        }
        verify(dataFetcher, times(2)).fetchAnalyticsData(any(Date.class), any(Date.class), any());
    }

    @Test
    public void serialisedParametersArePassedToTheDataFetcher() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        report.setParameters("{\"metric\":\"uploads\",\"region\":\"emea\"}");
        stubReport(report);
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(fileContaining("x"));

        Map<String, String> expected = new HashMap<>();
        expected.put("metric", "uploads");
        expected.put("region", "emea");
        when(dataFetcher.fetchAnalyticsData(report.getDateFrom(), report.getDateTo(), expected))
                .thenReturn(rows(1));

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        verify(dataFetcher).fetchAnalyticsData(report.getDateFrom(), report.getDateTo(), expected);
    }

    @Test
    public void rowsAreCappedAtTheConfiguredMaximum() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        stubReport(report);
        when(appConfig.getMaxRows()).thenReturn(2);
        when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
        when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), any())).thenReturn(rows(5));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(fileContaining("x"));

        worker.generateReportAsync(REPORT_ID);

        ArgumentCaptor<List> passedData = ArgumentCaptor.forClass(List.class);
        verify(csvGenerator).generateCsv(eq(report), passedData.capture(), anyString());
        assertEquals(2, passedData.getValue().size());
        assertEquals(Integer.valueOf(2), report.getRowCount());
    }

    @Test
    public void emptyDataStillProducesACompletedReport() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        stubReport(report);
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
        when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), any()))
                .thenReturn(Collections.<Map<String, Object>>emptyList());
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(fileContaining(""));

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        assertEquals(Integer.valueOf(0), report.getRowCount());
    }

    @Test
    public void generatorFailureMarksTheReportFailed() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        stubReport(report);
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn("/tmp/reports");
        when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), any())).thenReturn(rows(1));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString()))
                .thenThrow(new IOException("disk full"));

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals("disk full", report.getErrorMessage());
        assertNotNull(report.getCompletedAt());
        assertNull(report.getFilePath());
        verify(reportRepository, times(2)).save(report);
    }

    @Test
    public void malformedParametersJsonMarksTheReportFailed() {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        report.setParameters("{not-json");
        stubReport(report);

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertNotNull(report.getErrorMessage());
        verifyNoInteractions(dataFetcher, csvGenerator);
    }

    @Test
    public void downstreamFetchFailureMarksTheReportFailed() {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        stubReport(report);
        when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), any()))
                .thenThrow(new IllegalStateException("analytics unavailable"));

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals("analytics unavailable", report.getErrorMessage());
        verifyNoInteractions(csvGenerator, pdfGenerator, excelGenerator);
    }

    // ----- helpers -----

    private void stubReport(Report report) {
        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));
    }

    private Report report(ReportCategory category, ReportType type) {
        Report report = new Report();
        report.setId(REPORT_ID);
        report.setReportName("Worker Report");
        report.setCategory(category);
        report.setReportType(type);
        report.setRequestedBy("worker-user");
        report.setStatus(ReportStatus.PENDING);
        report.setCreatedAt(CREATED_AT);
        report.setDateFrom(new Date(CREATED_AT.getTime() - 86_400_000L));
        report.setDateTo(CREATED_AT);
        return report;
    }

    private File fileContaining(String content) throws IOException {
        File file = tempFolder.newFile();
        Files.write(file.toPath(), content.getBytes(StandardCharsets.UTF_8));
        assertTrue(file.exists());
        return file;
    }

    private static List<Map<String, Object>> rows(int count) {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            Map<String, Object> row = new HashMap<>();
            row.put("id", i);
            rows.add(row);
        }
        return rows;
    }
}
