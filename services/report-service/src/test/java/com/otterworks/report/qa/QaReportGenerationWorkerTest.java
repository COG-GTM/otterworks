package com.otterworks.report.qa;

import com.otterworks.report.config.AppConfig;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import com.otterworks.report.service.CsvReportGenerator;
import com.otterworks.report.service.ExcelReportGenerator;
import com.otterworks.report.service.PdfReportGenerator;
import com.otterworks.report.service.ReportDataFetcher;
import com.otterworks.report.service.ReportGenerationWorker;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

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
import static org.junit.Assert.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** QA audit: ReportGenerationWorker state machine and category routing (pure Mockito). */
public class QaReportGenerationWorkerTest {

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    private ReportRepository repo;
    private ReportDataFetcher fetcher;
    private PdfReportGenerator pdf;
    private CsvReportGenerator csv;
    private ExcelReportGenerator excel;
    private AppConfig appConfig;
    private ReportGenerationWorker worker;

    @Before
    public void setUp() {
        repo = mock(ReportRepository.class);
        fetcher = mock(ReportDataFetcher.class);
        pdf = mock(PdfReportGenerator.class);
        csv = mock(CsvReportGenerator.class);
        excel = mock(ExcelReportGenerator.class);
        appConfig = mock(AppConfig.class);
        when(appConfig.getMaxRows()).thenReturn(3);
        when(appConfig.getReportOutputDir()).thenReturn(tmp.getRoot().getAbsolutePath());
        when(repo.save(any(Report.class))).thenAnswer(inv -> inv.getArgument(0));
        worker = new ReportGenerationWorker(repo, fetcher, pdf, csv, excel, appConfig);
    }

    private Report report(ReportCategory category, ReportType type, String params) {
        Report r = new Report();
        r.setId(1L);
        r.setReportName("qa");
        r.setCategory(category);
        r.setReportType(type);
        r.setRequestedBy("u");
        r.setStatus(ReportStatus.PENDING);
        r.setCreatedAt(new Date());
        r.setDateFrom(new Date(0));
        r.setDateTo(new Date());
        r.setParameters(params);
        when(repo.findById(1L)).thenReturn(Optional.of(r));
        return r;
    }

    private static List<Map<String, Object>> rows(int n) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            Map<String, Object> m = new HashMap<>();
            m.put("i", i);
            out.add(m);
        }
        return out;
    }

    private File file(String name) throws IOException {
        File f = tmp.newFile(name);
        java.nio.file.Files.write(f.toPath(), "x".getBytes());
        return f;
    }

    @Test
    public void completesCsvReportAndTruncatesToMaxRows() throws Exception {
        Report r = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV, "{\"metric\":\"views\"}");
        when(fetcher.fetchAnalyticsData(any(), any(), any())).thenReturn(rows(10));
        File out = file("out.csv");
        when(csv.generateCsv(eq(r), anyList(), anyString())).thenReturn(out);

        worker.generateReportAsync(1L);

        assertEquals(ReportStatus.COMPLETED, r.getStatus());
        assertEquals(Integer.valueOf(3), r.getRowCount());
        assertEquals(out.getAbsolutePath(), r.getFilePath());
        assertEquals(Long.valueOf(1L), r.getFileSizeBytes());
        assertNotNull(r.getCompletedAt());
        verify(fetcher).fetchAnalyticsData(any(), any(), eq(Collections.singletonMap("metric", "views")));
    }

    @Test
    public void routesCategoriesToTheRightDataSource() throws Exception {
        when(fetcher.fetchAuditData(any(), any(), any())).thenReturn(rows(1));
        when(fetcher.fetchUserActivityData(any(), any(), any())).thenReturn(rows(1));
        when(pdf.generatePdf(any(), anyList(), anyString())).thenReturn(file("a.pdf"));
        when(excel.generateExcel(any(), anyList(), anyString())).thenReturn(file("b.xlsx"));

        report(ReportCategory.AUDIT_LOG, ReportType.PDF, null);
        worker.generateReportAsync(1L);
        verify(fetcher).fetchAuditData(any(), any(), isNull());

        Report r2 = report(ReportCategory.STORAGE_SUMMARY, ReportType.EXCEL, null);
        worker.generateReportAsync(1L);
        verify(fetcher).fetchUserActivityData(any(), any(), isNull());
        assertEquals(ReportStatus.COMPLETED, r2.getStatus());
        verify(fetcher, never()).fetchAnalyticsData(any(), any(), any());
    }

    @Test
    public void marksReportFailedWhenGenerationThrows() throws Exception {
        Report r = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV, null);
        when(fetcher.fetchAnalyticsData(any(), any(), any())).thenReturn(rows(2));
        when(csv.generateCsv(any(), anyList(), anyString())).thenThrow(new IOException("disk full"));

        worker.generateReportAsync(1L);

        assertEquals(ReportStatus.FAILED, r.getStatus());
        assertEquals("disk full", r.getErrorMessage());
        assertNotNull(r.getCompletedAt());
    }

    @Test
    public void marksReportFailedOnUnparseableParameters() {
        Report r = report(ReportCategory.USAGE_ANALYTICS, ReportType.CSV, "{not-json");
        worker.generateReportAsync(1L);
        assertEquals(ReportStatus.FAILED, r.getStatus());
    }

    @Test
    public void ignoresUnknownReportId() {
        when(repo.findById(99L)).thenReturn(Optional.empty());
        worker.generateReportAsync(99L);
        verify(repo, never()).save(any(Report.class));
    }
}
