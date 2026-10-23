package com.otterworks.report.service;

import com.google.common.util.concurrent.UncheckedExecutionException;
import com.otterworks.report.config.AppConfig;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportFailureReason;
import com.otterworks.report.model.ReportResponse;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;
import org.springframework.web.client.ResourceAccessException;

import java.net.ConnectException;
import java.util.Date;
import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@RunWith(MockitoJUnitRunner.class)
public class ReportGenerationWorkerTest {

    private static final String INTERNAL_URL =
            "http://analytics-service:8088/api/v1/analytics/events?from=2026-01-01&to=2026-01-31";

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
    public void downstreamFailureStoresReasonCodeNotExceptionText() {
        Report report = analyticsReport("{\"metric\":\"x\"}");
        when(reportRepository.findById(7L)).thenReturn(Optional.of(report));
        ResourceAccessException cause = new ResourceAccessException(
                "I/O error on GET request for \"" + INTERNAL_URL + "\": Connection refused",
                new ConnectException("Connection refused"));
        when(dataFetcher.fetchAnalyticsData(any(), any(), any()))
                .thenThrow(new UncheckedExecutionException(cause));

        worker.generateReportAsync(7L);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals("DATA_SOURCE_UNAVAILABLE", report.getErrorMessage());
        verify(reportRepository, atLeastOnce()).save(report);

        ReportResponse response = ReportResponse.fromEntity(report);
        assertEquals("DATA_SOURCE_UNAVAILABLE", response.getFailureReason());
        assertEquals(ReportFailureReason.DATA_SOURCE_UNAVAILABLE.getMessage(), response.getErrorMessage());
        assertFalse(response.getErrorMessage().contains("analytics-service"));
        assertFalse(response.getErrorMessage().contains("http://"));
    }

    @Test
    public void malformedParametersMapToInvalidParameters() {
        Report report = analyticsReport("{not json");
        when(reportRepository.findById(7L)).thenReturn(Optional.of(report));

        worker.generateReportAsync(7L);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals("INVALID_PARAMETERS", report.getErrorMessage());
    }

    @Test
    public void generatorFailureIsNotReportedAsInvalidParameters() throws Exception {
        Report report = analyticsReport(null);
        when(reportRepository.findById(7L)).thenReturn(Optional.of(report));
        when(appConfig.getMaxRows()).thenReturn(1000);
        when(pdfGenerator.generatePdf(any(), any(), any()))
                .thenThrow(new IllegalArgumentException("The number of columns in PdfPTable constructor must be greater than zero."));

        worker.generateReportAsync(7L);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals("GENERATION_FAILED", report.getErrorMessage());
    }

    @Test
    public void classifiesDownstreamErrorsByCauseChainOtherwiseUsesStage() {
        assertEquals(ReportFailureReason.DATA_SOURCE_UNAVAILABLE, ReportGenerationWorker.classifyFailure(
                new RuntimeException(new ResourceAccessException(INTERNAL_URL)), ReportFailureReason.GENERATION_FAILED));
        assertEquals(ReportFailureReason.GENERATION_FAILED, ReportGenerationWorker.classifyFailure(
                new UncheckedExecutionException(new IllegalArgumentException("Illegal character in query")),
                ReportFailureReason.GENERATION_FAILED));
        assertEquals(ReportFailureReason.INVALID_PARAMETERS, ReportGenerationWorker.classifyFailure(
                new RuntimeException("Unexpected character"), ReportFailureReason.INVALID_PARAMETERS));
    }

    private Report analyticsReport(String parameters) {
        Report report = new Report();
        report.setId(7L);
        report.setReportName("Usage");
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(ReportType.PDF);
        report.setRequestedBy("user-001");
        report.setCreatedAt(new Date());
        report.setDateFrom(new Date(0L));
        report.setDateTo(new Date());
        report.setParameters(parameters);
        return report;
    }
}
