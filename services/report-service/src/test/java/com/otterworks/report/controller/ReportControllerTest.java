package com.otterworks.report.controller;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportResponse;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.service.ReportService;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportController} with a mocked {@link ReportService}.
 *
 * These complement {@code ReportControllerIntegrationTest} (which drives the wired-up MVC stack)
 * by covering the status-code decision table of the download endpoint, which needs report states
 * and files that are awkward to reach through the full context.
 */
public class ReportControllerTest {

    private static final long REPORT_ID = 11L;

    /** 2024-01-01T00:00:00Z */
    private static final Date FROM = new Date(1_704_067_200_000L);

    /** 2024-01-08T00:00:00Z */
    private static final Date TO = new Date(1_704_672_000_000L);

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    @Mock
    private ReportService reportService;

    private AutoCloseable mocks;
    private ReportController controller;

    @Before
    public void setUp() {
        mocks = MockitoAnnotations.openMocks(this);
        controller = new ReportController(reportService);
    }

    @After
    public void tearDown() throws Exception {
        mocks.close();
    }

    // ----- POST /api/v1/reports -----

    @Test
    public void createReportReturnsAcceptedWithTheMappedResponse() {
        Report report = report(ReportStatus.PENDING, ReportType.PDF);
        ReportRequest request = new ReportRequest();
        request.setReportName("Weekly Usage");
        request.setCategory(ReportCategory.USAGE_ANALYTICS);
        request.setReportType(ReportType.PDF);
        request.setRequestedBy("user-1");
        when(reportService.createReport(request)).thenReturn(report);

        ResponseEntity<ReportResponse> response = controller.createReport(request);

        assertEquals(HttpStatus.ACCEPTED, response.getStatusCode());
        assertNotNull(response.getBody());
        assertEquals(Long.valueOf(REPORT_ID), response.getBody().getId());
        assertEquals("PENDING", response.getBody().getStatus());
    }

    // ----- GET /api/v1/reports/{id} -----

    @Test
    public void getReportReturnsTheMappedResponse() {
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.COMPLETED, ReportType.CSV)));

        ResponseEntity<ReportResponse> response = controller.getReport(REPORT_ID);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("COMPLETED", response.getBody().getStatus());
    }

    @Test
    public void getReportReturnsNotFoundForAnUnknownId() {
        when(reportService.getReport(REPORT_ID)).thenReturn(Optional.<Report>empty());

        assertEquals(HttpStatus.NOT_FOUND, controller.getReport(REPORT_ID).getStatusCode());
    }

    // ----- GET /api/v1/reports -----

    @Test
    public void listReportsFiltersByUserIdWhenSupplied() {
        List<Report> reports = Arrays.asList(
                report(ReportStatus.COMPLETED, ReportType.PDF), report(ReportStatus.FAILED, ReportType.CSV));
        when(reportService.getReportsByUser("user-1")).thenReturn(reports);

        ResponseEntity<Map<String, Object>> response = controller.listReports("user-1", null);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(2, response.getBody().get("total"));
        assertEquals(2, ((List<?>) response.getBody().get("reports")).size());
    }

    @Test
    public void listReportsFiltersByStatusWhenNoUserIdIsSupplied() {
        when(reportService.getReportsByStatus(ReportStatus.FAILED))
                .thenReturn(Collections.singletonList(report(ReportStatus.FAILED, ReportType.CSV)));

        ResponseEntity<Map<String, Object>> response = controller.listReports(null, ReportStatus.FAILED);

        assertEquals(1, response.getBody().get("total"));
    }

    @Test
    public void listReportsDefaultsToCompletedWhenNoFilterIsSupplied() {
        when(reportService.getReportsByStatus(ReportStatus.COMPLETED))
                .thenReturn(Collections.<Report>emptyList());

        ResponseEntity<Map<String, Object>> response = controller.listReports(null, null);

        assertEquals(0, response.getBody().get("total"));
        verify(reportService).getReportsByStatus(ReportStatus.COMPLETED);
    }

    // ----- GET /api/v1/reports/{id}/download -----

    @Test
    public void downloadReturnsNotFoundForAnUnknownId() {
        when(reportService.getReport(REPORT_ID)).thenReturn(Optional.<Report>empty());

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturnsConflictWhileTheReportIsStillPending() {
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.PENDING, ReportType.PDF)));

        assertEquals(HttpStatus.CONFLICT, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturnsConflictWhileTheReportIsGenerating() {
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.GENERATING, ReportType.PDF)));

        assertEquals(HttpStatus.CONFLICT, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturnsNotFoundForAFailedReport() {
        Report report = report(ReportStatus.FAILED, ReportType.PDF);
        report.setFilePath("/tmp/does-not-matter.pdf");
        when(reportService.getReport(REPORT_ID)).thenReturn(Optional.of(report));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturnsNotFoundWhenNoFileWasRecorded() {
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.COMPLETED, ReportType.PDF)));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturnsNotFoundWhenTheRecordedFileIsMissingOnDisk() {
        Report report = report(ReportStatus.COMPLETED, ReportType.PDF);
        report.setFilePath(new File(tmp.getRoot(), "vanished.pdf").getAbsolutePath());
        when(reportService.getReport(REPORT_ID)).thenReturn(Optional.of(report));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturnsNotFoundWhenTheFileCannotBeRead() throws Exception {
        // A directory passes File.exists() but fails on read, exercising the IOException branch.
        Report report = report(ReportStatus.COMPLETED, ReportType.PDF);
        report.setFilePath(tmp.newFolder("a-directory").getAbsolutePath());
        when(reportService.getReport(REPORT_ID)).thenReturn(Optional.of(report));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadServesAPdfWithTheCorrectContentTypeAndDisposition() throws Exception {
        ResponseEntity<Resource> response = downloadWith(ReportType.PDF, "usage.pdf");

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("application/pdf", response.getHeaders().getContentType().toString());
        assertEquals("attachment; filename=\"usage.pdf\"",
                response.getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION));
        assertEquals(5L, response.getHeaders().getContentLength());
        assertTrue(response.getBody().exists());
    }

    @Test
    public void downloadServesACsvWithTheCorrectContentType() throws Exception {
        ResponseEntity<Resource> response = downloadWith(ReportType.CSV, "usage.csv");

        assertEquals("text/csv", response.getHeaders().getContentType().toString());
    }

    @Test
    public void downloadServesAnExcelFileWithTheCorrectContentType() throws Exception {
        ResponseEntity<Resource> response = downloadWith(ReportType.EXCEL, "usage.xlsx");

        assertEquals("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                response.getHeaders().getContentType().toString());
    }

    // ----- DELETE /api/v1/reports/{id} -----

    @Test
    public void deleteReturnsNoContentWhenTheReportWasRemoved() {
        when(reportService.deleteReport(REPORT_ID)).thenReturn(true);

        ResponseEntity<Void> response = controller.deleteReport(REPORT_ID);

        assertEquals(HttpStatus.NO_CONTENT, response.getStatusCode());
        assertNull(response.getBody());
    }

    @Test
    public void deleteReturnsNotFoundForAnUnknownId() {
        when(reportService.deleteReport(REPORT_ID)).thenReturn(false);

        assertEquals(HttpStatus.NOT_FOUND, controller.deleteReport(REPORT_ID).getStatusCode());
    }

    // ----- helpers -----

    private ResponseEntity<Resource> downloadWith(ReportType type, String fileName) throws Exception {
        File file = tmp.newFile(fileName);
        Files.write(file.toPath(), "hello".getBytes(StandardCharsets.UTF_8));

        Report report = report(ReportStatus.COMPLETED, type);
        report.setFilePath(file.getAbsolutePath());
        when(reportService.getReport(REPORT_ID)).thenReturn(Optional.of(report));

        return controller.downloadReport(REPORT_ID);
    }

    private static Report report(ReportStatus status, ReportType type) {
        Report report = new Report();
        report.setId(REPORT_ID);
        report.setReportName("Weekly Usage");
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(type);
        report.setRequestedBy("user-1");
        report.setStatus(status);
        report.setCreatedAt(FROM);
        report.setDateFrom(FROM);
        report.setDateTo(TO);
        return report;
    }
}
