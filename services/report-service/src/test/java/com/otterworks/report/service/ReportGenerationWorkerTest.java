package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportGenerationWorker}.
 *
 * Every collaborator (repository, data fetcher, and the three file generators) is mocked, so the
 * worker is exercised synchronously with no database, HTTP, or report rendering involved. The
 * only filesystem use is a JUnit {@link TemporaryFolder} standing in for a generated file.
 */
public class ReportGenerationWorkerTest {

    private static final long REPORT_ID = 42L;

    /** 2024-01-01T00:00:00Z */
    private static final Date FROM = new Date(1_704_067_200_000L);

    /** 2024-01-08T00:00:00Z */
    private static final Date TO = new Date(1_704_672_000_000L);

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

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

    private AutoCloseable mocks;
    private ReportGenerationWorker worker;

    @Before
    public void setUp() {
        mocks = MockitoAnnotations.openMocks(this);
        worker = new ReportGenerationWorker(
                reportRepository, dataFetcher, pdfGenerator, csvGenerator, excelGenerator, appConfig);
    }

    @After
    public void tearDown() throws Exception {
        mocks.close();
    }

    @Test
    public void unknownReportIdIsIgnored() {
        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.<Report>empty());

        worker.generateReportAsync(REPORT_ID);

        verify(reportRepository, never()).save(any(Report.class));
    }

    @Test
    public void pdfReportIsGeneratedAndMarkedCompleted() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.PDF);
        File generated = tmp.newFile("report.pdf");
        writeBytes(generated, 7);

        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(eq(FROM), eq(TO), any())).thenReturn(rows(3));
        when(pdfGenerator.generatePdf(eq(report), anyList(), anyString())).thenReturn(generated);

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        assertEquals(generated.getAbsolutePath(), report.getFilePath());
        assertEquals(Long.valueOf(7L), report.getFileSizeBytes());
        assertEquals(Integer.valueOf(3), report.getRowCount());
        assertNull(report.getErrorMessage());
        assertTrue(report.getCompletedAt().getTime() >= report.getCreatedAt().getTime());

        // The report is marked GENERATING before the work starts, then COMPLETED afterwards.
        verify(reportRepository, org.mockito.Mockito.times(2)).save(report);
    }

    @Test
    public void csvReportIsRoutedToTheCsvGenerator() throws Exception {
        Report report = report(ReportCategory.AUDIT_LOG, ReportType.CSV);
        File generated = tmp.newFile("report.csv");

        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAuditData(eq(FROM), eq(TO), any())).thenReturn(rows(2));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(generated);

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        verify(csvGenerator).generateCsv(eq(report), anyList(), eq(tmp.getRoot().getAbsolutePath()));
    }

    @Test
    public void excelReportIsRoutedToTheExcelGenerator() throws Exception {
        Report report = report(ReportCategory.USER_ACTIVITY, ReportType.EXCEL);
        File generated = tmp.newFile("report.xlsx");

        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        when(dataFetcher.fetchUserActivityData(eq(FROM), eq(TO), any())).thenReturn(rows(1));
        when(excelGenerator.generateExcel(eq(report), anyList(), anyString())).thenReturn(generated);

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        verify(excelGenerator).generateExcel(eq(report), anyList(), anyString());
    }

    @Test
    public void collaborationMetricsCategoryUsesAnalyticsData() throws Exception {
        assertCategoryUsesAnalytics(ReportCategory.COLLABORATION_METRICS);
    }

    @Test
    public void systemHealthCategoryUsesAnalyticsData() throws Exception {
        assertCategoryUsesAnalytics(ReportCategory.SYSTEM_HEALTH);
    }

    private void assertCategoryUsesAnalytics(ReportCategory category) throws Exception {
        Report report = report(category, ReportType.CSV);

        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(eq(FROM), eq(TO), any())).thenReturn(rows(1));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString()))
                .thenReturn(tmp.newFile(category.name() + ".csv"));

        worker.generateReportAsync(REPORT_ID);

        verify(dataFetcher).fetchAnalyticsData(eq(FROM), eq(TO), any());
        assertEquals(ReportStatus.COMPLETED, report.getStatus());
    }

    @Test
    public void complianceCategoryUsesAuditData() throws Exception {
        Report report = report(ReportCategory.COMPLIANCE, ReportType.CSV);

        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAuditData(eq(FROM), eq(TO), any())).thenReturn(rows(1));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(tmp.newFile("c.csv"));

        worker.generateReportAsync(REPORT_ID);

        verify(dataFetcher).fetchAuditData(eq(FROM), eq(TO), any());
    }

    @Test
    public void storageSummaryCategoryUsesUserActivityData() throws Exception {
        Report report = report(ReportCategory.STORAGE_SUMMARY, ReportType.CSV);

        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        when(dataFetcher.fetchUserActivityData(eq(FROM), eq(TO), any())).thenReturn(rows(1));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(tmp.newFile("s.csv"));

        worker.generateReportAsync(REPORT_ID);

        verify(dataFetcher).fetchUserActivityData(eq(FROM), eq(TO), any());
    }

    @Test
    public void serialisedParametersArePassedThroughToTheDataFetcher() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        report.setParameters("{\"metric\":\"downloads\"}");

        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(eq(FROM), eq(TO), any())).thenReturn(rows(1));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(tmp.newFile("p.csv"));

        worker.generateReportAsync(REPORT_ID);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, String>> params = ArgumentCaptor.forClass(Map.class);
        verify(dataFetcher).fetchAnalyticsData(eq(FROM), eq(TO), params.capture());
        assertEquals(Collections.singletonMap("metric", "downloads"), params.getValue());
    }

    @Test
    public void dataIsTruncatedToTheConfiguredMaxRows() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);

        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(2);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(eq(FROM), eq(TO), any())).thenReturn(rows(5));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(tmp.newFile("t.csv"));

        worker.generateReportAsync(REPORT_ID);

        assertEquals(Integer.valueOf(2), report.getRowCount());
    }

    @Test
    public void malformedParametersMarkTheReportFailed() {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        report.setParameters("{not-json");

        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertTrue(report.getErrorMessage() != null && !report.getErrorMessage().isEmpty());
        verify(reportRepository, atLeastOnce()).save(report);
    }

    @Test
    public void generatorFailureMarksTheReportFailed() throws Exception {
        Report report = report(ReportCategory.USAGE_ANALYTICS, ReportType.PDF);

        when(reportRepository.findById(REPORT_ID)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(50_000);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(eq(FROM), eq(TO), any())).thenReturn(rows(1));
        when(pdfGenerator.generatePdf(eq(report), anyList(), anyString()))
                .thenThrow(new IOException("disk full"));

        worker.generateReportAsync(REPORT_ID);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals("disk full", report.getErrorMessage());
        assertNull(report.getFilePath());
    }

    // ----- helpers -----

    private Report report(ReportCategory category, ReportType type) {
        Report report = new Report();
        report.setId(REPORT_ID);
        report.setReportName("Weekly " + category.name());
        report.setCategory(category);
        report.setReportType(type);
        report.setRequestedBy("user-1");
        report.setStatus(ReportStatus.PENDING);
        report.setCreatedAt(FROM);
        report.setDateFrom(FROM);
        report.setDateTo(TO);
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

    private static void writeBytes(File file, int count) throws IOException {
        byte[] bytes = new byte[count];
        java.nio.file.Files.write(file.toPath(), bytes);
    }
}
