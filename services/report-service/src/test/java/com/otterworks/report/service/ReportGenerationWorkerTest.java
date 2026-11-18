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

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.util.ArrayList;
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
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class ReportGenerationWorkerTest {

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private ReportRepository repository;
    private ReportDataFetcher fetcher;
    private PdfReportGenerator pdf;
    private CsvReportGenerator csv;
    private ExcelReportGenerator excel;
    private AppConfig appConfig;
    private ReportGenerationWorker worker;
    private File outputFile;

    @Before
    public void setUp() throws IOException {
        repository = mock(ReportRepository.class);
        fetcher = mock(ReportDataFetcher.class);
        pdf = mock(PdfReportGenerator.class);
        csv = mock(CsvReportGenerator.class);
        excel = mock(ExcelReportGenerator.class);
        appConfig = mock(AppConfig.class);
        when(appConfig.getMaxRows()).thenReturn(1000);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        worker = new ReportGenerationWorker(repository, fetcher, pdf, csv, excel, appConfig);

        outputFile = tmp.newFile("out.bin");
        Files.write(outputFile.toPath(), new byte[]{1, 2, 3, 4});
    }

    private Report report(ReportCategory category, ReportType type) {
        Report r = new Report();
        r.setId(7L);
        r.setReportName("r");
        r.setCategory(category);
        r.setReportType(type);
        r.setStatus(ReportStatus.PENDING);
        r.setCreatedAt(new Date());
        r.setDateFrom(new Date(0));
        r.setDateTo(new Date());
        when(repository.findById(7L)).thenReturn(Optional.of(r));
        return r;
    }

    private static List<Map<String, Object>> rows(int n) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            Map<String, Object> row = new HashMap<>();
            row.put("i", i);
            list.add(row);
        }
        return list;
    }

    @Test
    public void missingReportIsIgnored() {
        when(repository.findById(1L)).thenReturn(Optional.empty());
        worker.generateReportAsync(1L);
        verify(repository, never()).save(any());
    }

    @Test
    public void analyticsCategoriesUseAnalyticsFetcherAndPdf() throws Exception {
        for (ReportCategory c : new ReportCategory[]{
                ReportCategory.USAGE_ANALYTICS, ReportCategory.COLLABORATION_METRICS, ReportCategory.SYSTEM_HEALTH}) {
            Report r = report(c, ReportType.PDF);
            when(fetcher.fetchAnalyticsData(any(), any(), isNull())).thenReturn(rows(3));
            when(pdf.generatePdf(eq(r), anyList(), anyString())).thenReturn(outputFile);

            worker.generateReportAsync(7L);

            assertEquals(ReportStatus.COMPLETED, r.getStatus());
            assertEquals(outputFile.getAbsolutePath(), r.getFilePath());
            assertEquals(Long.valueOf(4), r.getFileSizeBytes());
            assertEquals(Integer.valueOf(3), r.getRowCount());
            assertNotNull(r.getCompletedAt());
            assertNull(r.getErrorMessage());
        }
    }

    @Test
    public void auditCategoriesUseAuditFetcherAndCsvWithParameters() throws Exception {
        for (ReportCategory c : new ReportCategory[]{ReportCategory.AUDIT_LOG, ReportCategory.COMPLIANCE}) {
            Report r = report(c, ReportType.CSV);
            r.setParameters("{\"metric\":\"logins\"}");
            when(fetcher.fetchAuditData(any(), any(), eq(Collections.singletonMap("metric", "logins"))))
                    .thenReturn(rows(2));
            when(csv.generateCsv(eq(r), anyList(), anyString())).thenReturn(outputFile);

            worker.generateReportAsync(7L);

            assertEquals(ReportStatus.COMPLETED, r.getStatus());
            assertEquals(Integer.valueOf(2), r.getRowCount());
        }
    }

    @Test
    public void userCategoriesUseUserActivityFetcherAndExcel() throws Exception {
        for (ReportCategory c : new ReportCategory[]{ReportCategory.USER_ACTIVITY, ReportCategory.STORAGE_SUMMARY}) {
            Report r = report(c, ReportType.EXCEL);
            when(fetcher.fetchUserActivityData(any(), any(), isNull())).thenReturn(rows(1));
            when(excel.generateExcel(eq(r), anyList(), anyString())).thenReturn(outputFile);

            worker.generateReportAsync(7L);

            assertEquals(ReportStatus.COMPLETED, r.getStatus());
            verify(excel).generateExcel(eq(r), anyList(), eq(tmp.getRoot().getAbsolutePath()));
        }
    }

    @Test
    public void rowsAreTruncatedToMaxRows() throws Exception {
        when(appConfig.getMaxRows()).thenReturn(5);
        Report r = report(ReportCategory.USAGE_ANALYTICS, ReportType.PDF);
        when(fetcher.fetchAnalyticsData(any(), any(), any())).thenReturn(rows(12));
        when(pdf.generatePdf(eq(r), anyList(), anyString())).thenAnswer(inv -> {
            assertEquals(5, ((List<?>) inv.getArgument(1)).size());
            return outputFile;
        });

        worker.generateReportAsync(7L);

        assertEquals(ReportStatus.COMPLETED, r.getStatus());
        assertEquals(Integer.valueOf(5), r.getRowCount());
    }

    @Test
    public void generatorFailureMarksReportFailed() throws Exception {
        Report r = report(ReportCategory.USAGE_ANALYTICS, ReportType.PDF);
        when(fetcher.fetchAnalyticsData(any(), any(), any())).thenReturn(rows(1));
        when(pdf.generatePdf(any(), anyList(), anyString())).thenThrow(new IOException("disk full"));

        worker.generateReportAsync(7L);

        assertEquals(ReportStatus.FAILED, r.getStatus());
        assertEquals("disk full", r.getErrorMessage());
        assertNotNull(r.getCompletedAt());
        assertNull(r.getFilePath());
    }

    @Test
    public void malformedParametersMarkReportFailed() {
        Report r = report(ReportCategory.USAGE_ANALYTICS, ReportType.PDF);
        r.setParameters("{not json");

        worker.generateReportAsync(7L);

        assertEquals(ReportStatus.FAILED, r.getStatus());
        assertNotNull(r.getErrorMessage());
    }

    @Test
    public void fetcherFailureMarksReportFailed() {
        Report r = report(ReportCategory.AUDIT_LOG, ReportType.CSV);
        when(fetcher.fetchAuditData(any(), any(), any())).thenThrow(new IllegalStateException("upstream down"));

        worker.generateReportAsync(7L);

        assertEquals(ReportStatus.FAILED, r.getStatus());
        assertTrue(r.getErrorMessage().contains("upstream down"));
    }
}
