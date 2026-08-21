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
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;

import java.io.File;
import java.io.IOException;
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
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportGenerationWorker}.
 *
 * The repository, data fetcher and all three generators are mocked, so the test
 * exercises the orchestration logic (status transitions, category routing, row
 * capping and failure handling) without any I/O beyond a temporary output file.
 *
 * Written in JUnit 4 style to match the current stack.
 */
@RunWith(MockitoJUnitRunner.class)
public class ReportGenerationWorkerTest {

    private static final Date FROM = new Date(1704067200000L);
    private static final Date TO = new Date(1704153600000L);

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

    private Report report(Long id, ReportCategory category, ReportType type) {
        Report report = new Report();
        report.setId(id);
        report.setReportName("Report " + id);
        report.setCategory(category);
        report.setReportType(type);
        report.setStatus(ReportStatus.PENDING);
        report.setCreatedAt(new Date(1704067200000L));
        report.setDateFrom(FROM);
        report.setDateTo(TO);
        when(reportRepository.findById(id)).thenReturn(Optional.of(report));
        return report;
    }

    private static List<Map<String, Object>> rows(int count) {
        List<Map<String, Object>> data = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            Map<String, Object> row = new HashMap<>();
            row.put("id", i);
            data.add(row);
        }
        return data;
    }

    private File outputFile(String name, String content) throws IOException {
        File file = tempFolder.newFile(name);
        Files.write(file.toPath(), content.getBytes("UTF-8"));
        return file;
    }

    @Test
    public void missingReportIsLoggedAndSkipped() {
        when(reportRepository.findById(99L)).thenReturn(Optional.empty());

        worker.generateReportAsync(99L);

        verify(reportRepository, never()).save(any(Report.class));
        verifyNoInteractions(dataFetcher, pdfGenerator, csvGenerator, excelGenerator);
    }

    @Test
    public void analyticsCategoryGeneratesPdfAndCompletesTheReport() throws Exception {
        Report report = report(1L, ReportCategory.USAGE_ANALYTICS, ReportType.PDF);
        File file = outputFile("report.pdf", "pdf-bytes");
        when(appConfig.getMaxRows()).thenReturn(100);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(eq(FROM), eq(TO), isNull())).thenReturn(rows(3));
        when(pdfGenerator.generatePdf(eq(report), anyList(), anyString())).thenReturn(file);

        worker.generateReportAsync(1L);

        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        assertEquals(file.getAbsolutePath(), report.getFilePath());
        assertEquals(Long.valueOf(file.length()), report.getFileSizeBytes());
        assertEquals(Integer.valueOf(3), report.getRowCount());
        assertNotNull(report.getCompletedAt());
        assertNull(report.getErrorMessage());
        // Saved twice: once for GENERATING, once for the terminal state.
        verify(reportRepository, org.mockito.Mockito.times(2)).save(report);
    }

    @Test
    public void collaborationAndSystemHealthCategoriesAlsoUseAnalyticsData() throws Exception {
        Report collaboration = report(2L, ReportCategory.COLLABORATION_METRICS, ReportType.CSV);
        Report systemHealth = report(3L, ReportCategory.SYSTEM_HEALTH, ReportType.CSV);
        when(appConfig.getMaxRows()).thenReturn(100);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(eq(FROM), eq(TO), isNull())).thenReturn(rows(1));
        when(csvGenerator.generateCsv(any(Report.class), anyList(), anyString()))
                .thenReturn(outputFile("report.csv", "a,b"));

        worker.generateReportAsync(2L);
        worker.generateReportAsync(3L);

        assertEquals(ReportStatus.COMPLETED, collaboration.getStatus());
        assertEquals(ReportStatus.COMPLETED, systemHealth.getStatus());
        verify(dataFetcher, org.mockito.Mockito.times(2)).fetchAnalyticsData(eq(FROM), eq(TO), isNull());
    }

    @Test
    public void auditAndComplianceCategoriesUseAuditData() throws Exception {
        Report audit = report(4L, ReportCategory.AUDIT_LOG, ReportType.EXCEL);
        Report compliance = report(5L, ReportCategory.COMPLIANCE, ReportType.EXCEL);
        when(appConfig.getMaxRows()).thenReturn(100);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAuditData(eq(FROM), eq(TO), isNull())).thenReturn(rows(2));
        when(excelGenerator.generateExcel(any(Report.class), anyList(), anyString()))
                .thenReturn(outputFile("report.xlsx", "xlsx"));

        worker.generateReportAsync(4L);
        worker.generateReportAsync(5L);

        assertEquals(ReportStatus.COMPLETED, audit.getStatus());
        assertEquals(ReportStatus.COMPLETED, compliance.getStatus());
        verify(dataFetcher, org.mockito.Mockito.times(2)).fetchAuditData(eq(FROM), eq(TO), isNull());
        verifyNoInteractions(pdfGenerator, csvGenerator);
    }

    @Test
    public void userActivityAndStorageCategoriesUseUserActivityData() throws Exception {
        Report activity = report(6L, ReportCategory.USER_ACTIVITY, ReportType.CSV);
        Report storage = report(7L, ReportCategory.STORAGE_SUMMARY, ReportType.CSV);
        when(appConfig.getMaxRows()).thenReturn(100);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchUserActivityData(eq(FROM), eq(TO), isNull())).thenReturn(rows(4));
        when(csvGenerator.generateCsv(any(Report.class), anyList(), anyString()))
                .thenReturn(outputFile("activity.csv", "a,b,c"));

        worker.generateReportAsync(6L);
        worker.generateReportAsync(7L);

        assertEquals(ReportStatus.COMPLETED, activity.getStatus());
        assertEquals(ReportStatus.COMPLETED, storage.getStatus());
        assertEquals(Integer.valueOf(4), activity.getRowCount());
        verify(dataFetcher, org.mockito.Mockito.times(2)).fetchUserActivityData(eq(FROM), eq(TO), isNull());
    }

    @Test
    public void storedParametersArePassedToTheDataFetcher() throws Exception {
        Report report = report(8L, ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        report.setParameters("{\"metric\":\"uploads\"}");
        Map<String, String> expected = new HashMap<>();
        expected.put("metric", "uploads");
        when(appConfig.getMaxRows()).thenReturn(100);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(FROM, TO, expected)).thenReturn(rows(1));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString()))
                .thenReturn(outputFile("params.csv", "x"));

        worker.generateReportAsync(8L);

        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        verify(dataFetcher).fetchAnalyticsData(FROM, TO, expected);
    }

    @Test
    public void dataIsCappedAtTheConfiguredMaxRows() throws Exception {
        Report report = report(9L, ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        when(appConfig.getMaxRows()).thenReturn(2);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(eq(FROM), eq(TO), isNull())).thenReturn(rows(5));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString()))
                .thenReturn(outputFile("capped.csv", "x"));

        worker.generateReportAsync(9L);

        assertEquals(Integer.valueOf(2), report.getRowCount());
        verify(csvGenerator).generateCsv(eq(report), eq(rows(2)), anyString());
    }

    @Test
    public void generatorFailureMarksTheReportFailedWithTheErrorMessage() throws Exception {
        Report report = report(10L, ReportCategory.USAGE_ANALYTICS, ReportType.PDF);
        when(appConfig.getMaxRows()).thenReturn(100);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(eq(FROM), eq(TO), isNull()))
                .thenReturn(Collections.<Map<String, Object>>emptyList());
        when(pdfGenerator.generatePdf(eq(report), anyList(), anyString()))
                .thenThrow(new IOException("disk full"));

        worker.generateReportAsync(10L);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals("disk full", report.getErrorMessage());
        assertNotNull(report.getCompletedAt());
        assertNull(report.getFilePath());
    }

    @Test
    public void malformedStoredParametersMarkTheReportFailed() {
        Report report = report(11L, ReportCategory.USAGE_ANALYTICS, ReportType.PDF);
        report.setParameters("{not-json");

        worker.generateReportAsync(11L);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertNotNull(report.getErrorMessage());
        verifyNoInteractions(dataFetcher, pdfGenerator);
    }

    @Test
    public void aReportWithoutAnOutputFormatFails() throws Exception {
        Report report = report(12L, ReportCategory.AUDIT_LOG, null);
        when(appConfig.getMaxRows()).thenReturn(100);
        when(dataFetcher.fetchAuditData(eq(FROM), eq(TO), isNull()))
                .thenReturn(Arrays.<Map<String, Object>>asList(new HashMap<String, Object>()));

        worker.generateReportAsync(12L);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertNotNull(report.getCompletedAt());
        verifyNoInteractions(pdfGenerator, csvGenerator, excelGenerator);
    }

    @Test
    public void completedReportsRecordTheGeneratedFileSize() throws Exception {
        Report report = report(13L, ReportCategory.USAGE_ANALYTICS, ReportType.EXCEL);
        File file = outputFile("sized.xlsx", "0123456789");
        when(appConfig.getMaxRows()).thenReturn(100);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(eq(FROM), eq(TO), isNull())).thenReturn(rows(1));
        when(excelGenerator.generateExcel(eq(report), anyList(), anyString())).thenReturn(file);

        worker.generateReportAsync(13L);

        assertEquals(Long.valueOf(10L), report.getFileSizeBytes());
        assertTrue(report.getCompletedAt().getTime() >= report.getCreatedAt().getTime());
    }
}
