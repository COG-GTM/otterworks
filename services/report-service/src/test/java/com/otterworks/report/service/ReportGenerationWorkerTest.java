package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import org.junit.Before;
import org.junit.Test;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Verifies that an upstream fetch failure marks the report FAILED with an error message
 * for every category, instead of completing it with fabricated rows.
 */
public class ReportGenerationWorkerTest {

    private ReportRepository reportRepository;
    private final List<String> persisted = new ArrayList<>();
    private RestTemplate restTemplate;
    private ReportGenerationWorker worker;

    @Before
    public void setUp() {
        reportRepository = mock(ReportRepository.class);
        restTemplate = mock(RestTemplate.class);
        AppConfig appConfig = mock(AppConfig.class);
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics-test");
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit-test");
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth-test");
        when(appConfig.isSampleDataFallbackEnabled()).thenReturn(false);
        when(appConfig.getMaxRows()).thenReturn(50000);
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new HttpServerErrorException(HttpStatus.SERVICE_UNAVAILABLE));
        when(reportRepository.save(any(Report.class))).thenAnswer(inv -> {
            Report saved = inv.getArgument(0);
            persisted.add(saved.getStatus() + "|" + saved.getErrorMessage() + "|" + saved.getRowCount());
            return saved;
        });

        worker = new ReportGenerationWorker(reportRepository, new ReportDataFetcher(restTemplate, appConfig),
                mock(PdfReportGenerator.class), mock(CsvReportGenerator.class),
                mock(ExcelReportGenerator.class), appConfig);
    }

    @Test
    public void upstreamFailureMarksReportFailedForEveryCategory() {
        long id = 1;
        for (ReportCategory category : ReportCategory.values()) {
            Report report = report(id, category);
            when(reportRepository.findById(id)).thenReturn(Optional.of(report));
            persisted.clear();

            worker.generateReportAsync(id);

            String expectedError = "Failed to fetch " + expectedDataSet(category) + " data from "
                    + expectedUpstream(category);
            assertEquals(category.name(), ReportStatus.FAILED, report.getStatus());
            assertEquals(category.name(), expectedError, report.getErrorMessage());
            assertEquals(category.name(), "FAILED|" + expectedError + "|null",
                    persisted.get(persisted.size() - 1));
            assertNull(category.name(), report.getRowCount());
            assertNull(category.name(), report.getFilePath());
            id++;
        }
    }

    private static Report report(long id, ReportCategory category) {
        Report report = new Report();
        report.setId(id);
        report.setReportName("r-" + id);
        report.setCategory(category);
        report.setReportType(ReportType.CSV);
        report.setStatus(ReportStatus.PENDING);
        report.setRequestedBy("worker-test");
        report.setCreatedAt(new Date());
        report.setDateFrom(new Date(System.currentTimeMillis() - 86400000L));
        report.setDateTo(new Date());
        return report;
    }

    private static String expectedDataSet(ReportCategory category) {
        switch (category) {
            case AUDIT_LOG:
            case COMPLIANCE:
                return "audit";
            case USER_ACTIVITY:
            case STORAGE_SUMMARY:
                return "user activity";
            default:
                return "analytics";
        }
    }

    private static String expectedUpstream(ReportCategory category) {
        switch (expectedDataSet(category)) {
            case "audit":
                return "audit-service";
            case "user activity":
                return "auth-service";
            default:
                return "analytics-service";
        }
    }
}
