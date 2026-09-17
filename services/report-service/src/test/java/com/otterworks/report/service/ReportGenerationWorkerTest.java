package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportResponse;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;

import java.util.Date;
import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@RunWith(MockitoJUnitRunner.class)
public class ReportGenerationWorkerTest {

    private static final String SENSITIVE_DETAIL =
            "could not extract ResultSet; SQL [select * from audit_logs where actor_id = ?]; "
                    + "nested exception is org.postgresql.util.PSQLException: FATAL: password authentication "
                    + "failed for user \"report_svc\" (jdbc:postgresql://otterworks-dev.internal:5432/otterworks_dev)";

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
    public void failedReportDoesNotExposeTheUnderlyingExceptionDetail() {
        Report report = new Report();
        report.setId(42L);
        report.setReportName("Audit Log Export");
        report.setCategory(ReportCategory.AUDIT_LOG);
        report.setReportType(ReportType.CSV);
        report.setRequestedBy("attacker-001");
        report.setCreatedAt(new Date());
        report.setDateFrom(new Date(0L));
        report.setDateTo(new Date());

        when(reportRepository.findById(42L)).thenReturn(Optional.of(report));
        when(dataFetcher.fetchAuditData(any(), any(), any()))
                .thenThrow(new RuntimeException(SENSITIVE_DETAIL));

        worker.generateReportAsync(42L);

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals(ReportGenerationWorker.FAILURE_MESSAGE, report.getErrorMessage());

        String exposed = ReportResponse.fromEntity(report).getErrorMessage();
        assertFalse(exposed.contains("jdbc:postgresql"));
        assertFalse(exposed.contains("PSQLException"));
        assertFalse(exposed.contains("select * from audit_logs"));
        assertFalse(exposed.contains("report_svc"));
    }
}
