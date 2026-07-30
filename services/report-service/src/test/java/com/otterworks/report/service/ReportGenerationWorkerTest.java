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
import org.mockito.invocation.InvocationOnMock;
import org.mockito.junit.MockitoJUnitRunner;
import org.mockito.stubbing.Answer;

import java.io.File;
import java.io.IOException;
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
import static org.junit.Assert.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportGenerationWorker}.
 *
 * Every collaborator (repository, data fetcher, three generators, config) is mocked, so the
 * test exercises the orchestration logic — status transitions, category/type routing, row
 * capping and failure handling — without a Spring context, HTTP or a database.
 */
@RunWith(MockitoJUnitRunner.class)
public class ReportGenerationWorkerTest {

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
    public void doesNothingWhenTheReportIsGone() {
        when(reportRepository.findById(404L)).thenReturn(Optional.<Report>empty());

        worker.generateReportAsync(404L);

        verify(reportRepository, never()).save(any(Report.class));
        verifyNoInteractions(dataFetcher, csvGenerator, pdfGenerator, excelGenerator);
    }

    @Test
    public void marksTheReportGeneratingThenCompletedAndRecordsTheOutputFile() throws Exception {
        Report report = report(1L, ReportCategory.AUDIT_LOG, ReportType.CSV);
        report.setCreatedAt(new Date(1_704_067_200_000L));
        when(reportRepository.findById(1L)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(1000);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAuditData(any(Date.class), any(Date.class), isNull()))
                .thenReturn(rows(3));
        File generated = writeFile("audit.csv", "a,b,c");
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString())).thenReturn(generated);

        // The entity is mutated in place, so record the status at each save call.
        final List<ReportStatus> statusesAtSave = new ArrayList<ReportStatus>();
        when(reportRepository.save(any(Report.class))).thenAnswer(new Answer<Report>() {
            @Override
            public Report answer(InvocationOnMock invocation) {
                Report saved = invocation.getArgument(0);
                statusesAtSave.add(saved.getStatus());
                return saved;
            }
        });

        worker.generateReportAsync(1L);

        assertEquals(Arrays.asList(ReportStatus.GENERATING, ReportStatus.COMPLETED), statusesAtSave);
        assertEquals(generated.getAbsolutePath(), report.getFilePath());
        assertEquals(Long.valueOf(generated.length()), report.getFileSizeBytes());
        assertEquals(Integer.valueOf(3), report.getRowCount());
        assertNotNull(report.getCompletedAt());
    }

    @Test
    public void deserialisesJsonParametersAndForwardsThemToTheFetcher() throws Exception {
        Report report = report(2L, ReportCategory.USAGE_ANALYTICS, ReportType.CSV);
        report.setParameters("{\"metric\":\"uploads\"}");
        when(reportRepository.findById(2L)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(1000);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), any(Map.class)))
                .thenReturn(rows(1));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString()))
                .thenReturn(writeFile("analytics.csv", "x"));

        worker.generateReportAsync(2L);

        ArgumentCaptor<Map> params = ArgumentCaptor.forClass(Map.class);
        verify(dataFetcher).fetchAnalyticsData(any(Date.class), any(Date.class), params.capture());
        assertEquals("uploads", params.getValue().get("metric"));
    }

    @Test
    public void capsTheDataSetAtTheConfiguredMaximumRowCount() throws Exception {
        Report report = report(3L, ReportCategory.COMPLIANCE, ReportType.CSV);
        when(reportRepository.findById(3L)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(2);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAuditData(any(Date.class), any(Date.class), isNull()))
                .thenReturn(rows(5));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString()))
                .thenReturn(writeFile("capped.csv", "x"));

        worker.generateReportAsync(3L);

        ArgumentCaptor<List> data = ArgumentCaptor.forClass(List.class);
        verify(csvGenerator).generateCsv(eq(report), data.capture(), anyString());
        assertEquals(2, data.getValue().size());
        assertEquals(Integer.valueOf(2), report.getRowCount());
    }

    @Test
    public void routesAnalyticsCategoriesToTheAnalyticsEndpoint() throws Exception {
        for (ReportCategory category : Arrays.asList(
                ReportCategory.USAGE_ANALYTICS, ReportCategory.COLLABORATION_METRICS, ReportCategory.SYSTEM_HEALTH)) {
            runCsvReport(category);
        }

        verify(dataFetcher, times(3)).fetchAnalyticsData(any(Date.class), any(Date.class), isNull());
        verify(dataFetcher, never()).fetchAuditData(any(Date.class), any(Date.class), isNull());
        verify(dataFetcher, never()).fetchUserActivityData(any(Date.class), any(Date.class), isNull());
    }

    @Test
    public void routesAuditCategoriesToTheAuditEndpoint() throws Exception {
        for (ReportCategory category : Arrays.asList(ReportCategory.AUDIT_LOG, ReportCategory.COMPLIANCE)) {
            runCsvReport(category);
        }

        verify(dataFetcher, times(2)).fetchAuditData(any(Date.class), any(Date.class), isNull());
        verify(dataFetcher, never()).fetchAnalyticsData(any(Date.class), any(Date.class), isNull());
    }

    @Test
    public void routesUserCategoriesToTheUserActivityEndpoint() throws Exception {
        for (ReportCategory category : Arrays.asList(ReportCategory.USER_ACTIVITY, ReportCategory.STORAGE_SUMMARY)) {
            runCsvReport(category);
        }

        verify(dataFetcher, times(2)).fetchUserActivityData(any(Date.class), any(Date.class), isNull());
        verify(dataFetcher, never()).fetchAnalyticsData(any(Date.class), any(Date.class), isNull());
    }

    @Test
    public void routesPdfReportsToThePdfGenerator() throws Exception {
        Report report = report(10L, ReportCategory.USAGE_ANALYTICS, ReportType.PDF);
        when(reportRepository.findById(10L)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(1000);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), isNull())).thenReturn(rows(1));
        when(pdfGenerator.generatePdf(eq(report), anyList(), anyString()))
                .thenReturn(writeFile("report.pdf", "%PDF"));

        worker.generateReportAsync(10L);

        verify(pdfGenerator).generatePdf(eq(report), anyList(), anyString());
        assertEquals(ReportStatus.COMPLETED, report.getStatus());
    }

    @Test
    public void routesExcelReportsToTheExcelGenerator() throws Exception {
        Report report = report(11L, ReportCategory.STORAGE_SUMMARY, ReportType.EXCEL);
        when(reportRepository.findById(11L)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(1000);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchUserActivityData(any(Date.class), any(Date.class), isNull())).thenReturn(rows(1));
        when(excelGenerator.generateExcel(eq(report), anyList(), anyString()))
                .thenReturn(writeFile("report.xlsx", "PK"));

        worker.generateReportAsync(11L);

        verify(excelGenerator).generateExcel(eq(report), anyList(), anyString());
        assertEquals(ReportStatus.COMPLETED, report.getStatus());
    }

    @Test
    public void marksTheReportFailedWhenGenerationThrows() throws Exception {
        Report report = report(12L, ReportCategory.AUDIT_LOG, ReportType.CSV);
        when(reportRepository.findById(12L)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(1000);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(dataFetcher.fetchAuditData(any(Date.class), any(Date.class), isNull())).thenReturn(rows(1));
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString()))
                .thenThrow(new IOException("disk full"));

        worker.generateReportAsync(12L);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals("disk full", report.getErrorMessage());
        assertNotNull(report.getCompletedAt());
        verify(reportRepository, times(2)).save(report);
    }

    @Test
    public void marksTheReportFailedWhenTheStoredParametersAreNotValidJson() {
        Report report = report(13L, ReportCategory.AUDIT_LOG, ReportType.CSV);
        report.setParameters("this-is-not-json");
        when(reportRepository.findById(13L)).thenReturn(Optional.of(report));

        worker.generateReportAsync(13L);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertTrue(report.getErrorMessage(), report.getErrorMessage().length() > 0);
        verifyNoInteractions(csvGenerator);
    }

    // ----- helpers -----

    private void runCsvReport(ReportCategory category) throws IOException {
        long id = 100 + category.ordinal();
        Report report = report(id, category, ReportType.CSV);
        when(reportRepository.findById(id)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(1000);
        when(appConfig.getReportOutputDir()).thenReturn(tempFolder.getRoot().getAbsolutePath());
        when(csvGenerator.generateCsv(eq(report), anyList(), anyString()))
                .thenReturn(writeFile("routed-" + id + ".csv", "x"));

        switch (category) {
            case USAGE_ANALYTICS:
            case COLLABORATION_METRICS:
            case SYSTEM_HEALTH:
                when(dataFetcher.fetchAnalyticsData(any(Date.class), any(Date.class), isNull())).thenReturn(rows(1));
                break;
            case AUDIT_LOG:
            case COMPLIANCE:
                when(dataFetcher.fetchAuditData(any(Date.class), any(Date.class), isNull())).thenReturn(rows(1));
                break;
            default:
                when(dataFetcher.fetchUserActivityData(any(Date.class), any(Date.class), isNull())).thenReturn(rows(1));
                break;
        }

        worker.generateReportAsync(id);
        assertEquals(ReportStatus.COMPLETED, report.getStatus());
    }

    private File writeFile(String name, String content) throws IOException {
        File file = tempFolder.newFile(name);
        org.apache.commons.io.FileUtils.writeStringToFile(file, content, "UTF-8");
        return file;
    }

    private static Report report(Long id, ReportCategory category, ReportType type) {
        Report report = new Report();
        report.setId(id);
        report.setReportName("Report " + id);
        report.setCategory(category);
        report.setReportType(type);
        report.setStatus(ReportStatus.PENDING);
        report.setRequestedBy("user-1");
        report.setCreatedAt(new Date(1_704_067_200_000L));
        report.setDateFrom(new Date(1_704_067_200_000L));
        report.setDateTo(new Date(1_706_745_600_000L));
        return report;
    }

    private static List<Map<String, Object>> rows(int count) {
        List<Map<String, Object>> rows = new ArrayList<Map<String, Object>>();
        for (int i = 0; i < count; i++) {
            Map<String, Object> row = new HashMap<String, Object>();
            row.put("id", "row-" + i);
            rows.add(row);
        }
        return Collections.unmodifiableList(rows);
    }
}
