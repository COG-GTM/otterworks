package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import org.junit.Test;
import org.springframework.web.client.ResourceAccessException;

import java.util.Date;
import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

public class ReportGenerationWorkerTest {

    @Test
    public void failedGenerationStoresGenericErrorInsteadOfExceptionText() {
        ReportRepository repository = mock(ReportRepository.class);
        ReportDataFetcher dataFetcher = mock(ReportDataFetcher.class);

        Report report = new Report();
        report.setId(42L);
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(ReportType.CSV);
        report.setDateFrom(new Date());
        report.setDateTo(new Date());
        when(repository.findById(42L)).thenReturn(Optional.of(report));
        when(dataFetcher.fetchAnalyticsData(any(), any(), any()))
                .thenThrow(new ResourceAccessException(
                        "I/O error on GET request for \"http://analytics-service:8088/api/v1/analytics/dashboard\""));

        ReportGenerationWorker worker = new ReportGenerationWorker(
                repository, dataFetcher,
                mock(PdfReportGenerator.class), mock(CsvReportGenerator.class),
                mock(ExcelReportGenerator.class), mock(AppConfig.class));

        worker.generateReportAsync(42L);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals(Report.GENERATION_FAILED_MESSAGE, report.getErrorMessage());
    }
}
