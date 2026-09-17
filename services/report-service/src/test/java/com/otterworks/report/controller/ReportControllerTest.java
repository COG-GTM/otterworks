package com.otterworks.report.controller;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportResponse;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.service.ReportService;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
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
 * Unit tests for {@link ReportController}.
 *
 * The controller is exercised directly against a mocked {@link ReportService} — no Spring
 * context, no HTTP server — so every status-code branch (including the download error paths)
 * can be asserted cheaply. The MockMvc-based happy paths live in
 * {@link ReportControllerIntegrationTest}.
 */
@RunWith(MockitoJUnitRunner.class)
public class ReportControllerTest {

    private static final Long REPORT_ID = 7L;

    @Rule
    public TemporaryFolder tempFolder = new TemporaryFolder();

    @Mock
    private ReportService reportService;

    @InjectMocks
    private ReportController controller;

    // ----- POST /api/v1/reports -----

    @Test
    public void createReportReturns202WithTheCreatedResource() {
        ReportRequest request = new ReportRequest();
        request.setReportName("Quarterly usage");
        request.setCategory(ReportCategory.USAGE_ANALYTICS);
        request.setReportType(ReportType.PDF);
        request.setRequestedBy("user-1");

        Report created = report(ReportStatus.PENDING, ReportType.PDF, null);
        when(reportService.createReport(request)).thenReturn(created);

        ResponseEntity<ReportResponse> response = controller.createReport(request);

        assertEquals(HttpStatus.ACCEPTED, response.getStatusCode());
        assertNotNull(response.getBody());
        assertEquals(REPORT_ID, response.getBody().getId());
        assertEquals("PENDING", response.getBody().getStatus());
        assertNull("no file yet, so no download URL", response.getBody().getDownloadUrl());
        verify(reportService).createReport(request);
    }

    // ----- GET /api/v1/reports/{id} -----

    @Test
    public void getReportReturnsTheMappedReport() {
        Report report = report(ReportStatus.COMPLETED, ReportType.CSV, "/tmp/report.csv");
        when(reportService.getReport(REPORT_ID)).thenReturn(Optional.of(report));

        ResponseEntity<ReportResponse> response = controller.getReport(REPORT_ID);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("COMPLETED", response.getBody().getStatus());
        assertEquals("/api/v1/reports/7/download", response.getBody().getDownloadUrl());
    }

    @Test
    public void getReportReturns404WhenMissing() {
        when(reportService.getReport(REPORT_ID)).thenReturn(Optional.empty());

        ResponseEntity<ReportResponse> response = controller.getReport(REPORT_ID);

        assertEquals(HttpStatus.NOT_FOUND, response.getStatusCode());
        assertNull(response.getBody());
    }

    // ----- GET /api/v1/reports -----

    @Test
    public void listReportsFiltersByUserIdWhenProvided() {
        List<Report> reports = Arrays.asList(
                report(ReportStatus.COMPLETED, ReportType.CSV, "/tmp/a.csv"),
                report(ReportStatus.FAILED, ReportType.PDF, null));
        when(reportService.getReportsByUser("user-1")).thenReturn(reports);

        ResponseEntity<Map<String, Object>> response = controller.listReports("user-1", ReportStatus.FAILED);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(2, response.getBody().get("total"));
        assertEquals(2, ((List<?>) response.getBody().get("reports")).size());
    }

    @Test
    public void listReportsFiltersByStatusWhenNoUserIdIsGiven() {
        when(reportService.getReportsByStatus(ReportStatus.GENERATING))
                .thenReturn(Arrays.asList(report(ReportStatus.GENERATING, ReportType.CSV, null)));

        ResponseEntity<Map<String, Object>> response = controller.listReports(null, ReportStatus.GENERATING);

        assertEquals(1, response.getBody().get("total"));
        verify(reportService).getReportsByStatus(ReportStatus.GENERATING);
    }

    @Test
    public void listReportsDefaultsToCompletedReports() {
        when(reportService.getReportsByStatus(ReportStatus.COMPLETED))
                .thenReturn(java.util.Collections.<Report>emptyList());

        ResponseEntity<Map<String, Object>> response = controller.listReports(null, null);

        assertEquals(0, response.getBody().get("total"));
        assertTrue(((List<?>) response.getBody().get("reports")).isEmpty());
        verify(reportService).getReportsByStatus(ReportStatus.COMPLETED);
    }

    // ----- GET /api/v1/reports/{id}/download -----

    @Test
    public void downloadReturnsTheFileWithCsvContentType() throws Exception {
        File file = fileContaining("report.csv", "id,name\n1,alpha\n");
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.COMPLETED, ReportType.CSV, file.getAbsolutePath())));

        ResponseEntity<Resource> response = controller.downloadReport(REPORT_ID);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("text/csv", response.getHeaders().getContentType().toString());
        assertEquals("attachment; filename=\"report.csv\"",
                response.getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION));
        assertEquals(file.length(), response.getHeaders().getContentLength());
        assertEquals("id,name\n1,alpha\n",
                new String(readAll(response.getBody()), StandardCharsets.UTF_8));
    }

    @Test
    public void downloadUsesThePdfContentTypeForPdfReports() throws Exception {
        File file = fileContaining("report.pdf", "%PDF-1.4");
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.COMPLETED, ReportType.PDF, file.getAbsolutePath())));

        ResponseEntity<Resource> response = controller.downloadReport(REPORT_ID);

        assertEquals("application/pdf", response.getHeaders().getContentType().toString());
    }

    @Test
    public void downloadUsesTheSpreadsheetContentTypeForExcelReports() throws Exception {
        File file = fileContaining("report.xlsx", "PK");
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.COMPLETED, ReportType.EXCEL, file.getAbsolutePath())));

        ResponseEntity<Resource> response = controller.downloadReport(REPORT_ID);

        assertEquals("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                response.getHeaders().getContentType().toString());
    }

    @Test
    public void downloadReturns404ForAnUnknownReport() {
        when(reportService.getReport(REPORT_ID)).thenReturn(Optional.empty());

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturns409WhileTheReportIsStillBeingGenerated() {
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.GENERATING, ReportType.CSV, "/tmp/x.csv")));

        assertEquals(HttpStatus.CONFLICT, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturns409WhileTheReportIsStillPending() {
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.PENDING, ReportType.CSV, null)));

        assertEquals(HttpStatus.CONFLICT, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturns404ForAFailedReport() {
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.FAILED, ReportType.CSV, "/tmp/x.csv")));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturns404WhenTheReportHasNoFilePath() {
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.COMPLETED, ReportType.CSV, null)));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturns404WhenTheFileHasDisappeared() {
        String missing = new File(tempFolder.getRoot(), "gone.csv").getAbsolutePath();
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.COMPLETED, ReportType.CSV, missing)));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void downloadReturns404WhenTheFileCannotBeRead() throws Exception {
        // A directory passes File.exists() but cannot be read as a byte array.
        File directory = tempFolder.newFolder("not-a-file.csv");
        when(reportService.getReport(REPORT_ID))
                .thenReturn(Optional.of(report(ReportStatus.COMPLETED, ReportType.CSV,
                        directory.getAbsolutePath())));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(REPORT_ID).getStatusCode());
    }

    // ----- DELETE /api/v1/reports/{id} -----

    @Test
    public void deleteReturns204WhenTheReportWasDeleted() {
        when(reportService.deleteReport(REPORT_ID)).thenReturn(true);

        assertEquals(HttpStatus.NO_CONTENT, controller.deleteReport(REPORT_ID).getStatusCode());
    }

    @Test
    public void deleteReturns404WhenTheReportDoesNotExist() {
        when(reportService.deleteReport(REPORT_ID)).thenReturn(false);

        assertEquals(HttpStatus.NOT_FOUND, controller.deleteReport(REPORT_ID).getStatusCode());
    }

    // ----- helpers -----

    private Report report(ReportStatus status, ReportType type, String filePath) {
        Report report = new Report();
        report.setId(REPORT_ID);
        report.setReportName("Controller Report");
        report.setCategory(ReportCategory.AUDIT_LOG);
        report.setReportType(type);
        report.setStatus(status);
        report.setRequestedBy("user-1");
        report.setCreatedAt(new Date(1_704_067_200_000L));
        report.setFilePath(filePath);
        return report;
    }

    private File fileContaining(String name, String content) throws IOException {
        File file = tempFolder.newFile(name);
        Files.write(file.toPath(), content.getBytes(StandardCharsets.UTF_8));
        return file;
    }

    private static byte[] readAll(Resource resource) throws IOException {
        return org.apache.commons.io.IOUtils.toByteArray(resource.getInputStream());
    }
}
