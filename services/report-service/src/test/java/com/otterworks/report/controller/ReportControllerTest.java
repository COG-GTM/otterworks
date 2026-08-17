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
 * Unit tests for {@link ReportController} with the service layer mocked.
 *
 * Complements the existing Spring integration test by covering the response
 * mapping and every download branch (missing report, in-progress, failed,
 * missing file, and each content type) without booting a context.
 *
 * Written in JUnit 4 style to match the current stack.
 */
@RunWith(MockitoJUnitRunner.class)
public class ReportControllerTest {

    @Rule
    public TemporaryFolder tempFolder = new TemporaryFolder();

    @Mock
    private ReportService reportService;

    @InjectMocks
    private ReportController controller;

    private Report report(Long id, ReportStatus status, ReportType type) {
        Report report = new Report();
        report.setId(id);
        report.setReportName("Usage Report");
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(type);
        report.setStatus(status);
        report.setRequestedBy("user-1");
        report.setCreatedAt(new Date(1704067200000L));
        return report;
    }

    @Test
    public void createReportReturns202WithTheMappedResponse() {
        ReportRequest request = new ReportRequest();
        request.setReportName("Usage Report");
        request.setCategory(ReportCategory.USAGE_ANALYTICS);
        request.setReportType(ReportType.PDF);
        request.setRequestedBy("user-1");
        when(reportService.createReport(request)).thenReturn(report(1L, ReportStatus.PENDING, ReportType.PDF));

        ResponseEntity<ReportResponse> response = controller.createReport(request);

        assertEquals(HttpStatus.ACCEPTED, response.getStatusCode());
        assertEquals(Long.valueOf(1L), response.getBody().getId());
        assertEquals("PENDING", response.getBody().getStatus());
        assertEquals("PDF", response.getBody().getReportType());
    }

    @Test
    public void getReportReturnsTheMappedReport() {
        when(reportService.getReport(2L)).thenReturn(Optional.of(report(2L, ReportStatus.COMPLETED, ReportType.CSV)));

        ResponseEntity<ReportResponse> response = controller.getReport(2L);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("Usage Report", response.getBody().getReportName());
        assertEquals("COMPLETED", response.getBody().getStatus());
    }

    @Test
    public void getReportReturns404WhenUnknown() {
        when(reportService.getReport(404L)).thenReturn(Optional.empty());

        ResponseEntity<ReportResponse> response = controller.getReport(404L);

        assertEquals(HttpStatus.NOT_FOUND, response.getStatusCode());
        assertNull(response.getBody());
    }

    @Test
    public void listReportsFiltersByUserWhenUserIdIsGiven() {
        List<Report> reports = Arrays.asList(
                report(3L, ReportStatus.COMPLETED, ReportType.PDF),
                report(4L, ReportStatus.FAILED, ReportType.CSV));
        when(reportService.getReportsByUser("user-1")).thenReturn(reports);

        ResponseEntity<Map<String, Object>> response = controller.listReports("user-1", null);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(2, response.getBody().get("total"));
        assertEquals(2, ((List<?>) response.getBody().get("reports")).size());
    }

    @Test
    public void listReportsFiltersByStatusWhenOnlyStatusIsGiven() {
        when(reportService.getReportsByStatus(ReportStatus.FAILED))
                .thenReturn(Arrays.asList(report(5L, ReportStatus.FAILED, ReportType.PDF)));

        ResponseEntity<Map<String, Object>> response = controller.listReports(null, ReportStatus.FAILED);

        assertEquals(1, response.getBody().get("total"));
        verify(reportService).getReportsByStatus(ReportStatus.FAILED);
    }

    @Test
    public void listReportsDefaultsToCompletedReports() {
        when(reportService.getReportsByStatus(ReportStatus.COMPLETED))
                .thenReturn(Arrays.asList(report(6L, ReportStatus.COMPLETED, ReportType.PDF)));

        ResponseEntity<Map<String, Object>> response = controller.listReports(null, null);

        assertEquals(1, response.getBody().get("total"));
        verify(reportService).getReportsByStatus(ReportStatus.COMPLETED);
    }

    @Test
    public void downloadReturns404WhenTheReportDoesNotExist() {
        when(reportService.getReport(404L)).thenReturn(Optional.empty());

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(404L).getStatusCode());
    }

    @Test
    public void downloadReturns409WhileTheReportIsStillBeingGenerated() {
        when(reportService.getReport(7L)).thenReturn(Optional.of(report(7L, ReportStatus.GENERATING, ReportType.PDF)));
        when(reportService.getReport(8L)).thenReturn(Optional.of(report(8L, ReportStatus.PENDING, ReportType.PDF)));

        assertEquals(HttpStatus.CONFLICT, controller.downloadReport(7L).getStatusCode());
        assertEquals(HttpStatus.CONFLICT, controller.downloadReport(8L).getStatusCode());
    }

    @Test
    public void downloadReturns404ForFailedReports() {
        Report failed = report(9L, ReportStatus.FAILED, ReportType.PDF);
        failed.setErrorMessage("boom");
        when(reportService.getReport(9L)).thenReturn(Optional.of(failed));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(9L).getStatusCode());
    }

    @Test
    public void downloadReturns404WhenTheCompletedReportHasNoFilePath() {
        when(reportService.getReport(10L)).thenReturn(Optional.of(report(10L, ReportStatus.COMPLETED, ReportType.PDF)));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(10L).getStatusCode());
    }

    @Test
    public void downloadReturns404WhenTheFileIsMissingOnDisk() throws Exception {
        Report completed = report(11L, ReportStatus.COMPLETED, ReportType.PDF);
        completed.setFilePath(new File(tempFolder.getRoot(), "not-there.pdf").getAbsolutePath());
        when(reportService.getReport(11L)).thenReturn(Optional.of(completed));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(11L).getStatusCode());
    }

    @Test
    public void downloadStreamsThePdfWithAnAttachmentHeader() throws Exception {
        File file = tempFolder.newFile("usage.pdf");
        Files.write(file.toPath(), "pdf-bytes".getBytes("UTF-8"));
        Report completed = report(12L, ReportStatus.COMPLETED, ReportType.PDF);
        completed.setFilePath(file.getAbsolutePath());
        when(reportService.getReport(12L)).thenReturn(Optional.of(completed));

        ResponseEntity<Resource> response = controller.downloadReport(12L);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("application/pdf", response.getHeaders().getContentType().toString());
        assertEquals("attachment; filename=\"usage.pdf\"",
                response.getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION));
        assertEquals(9L, response.getHeaders().getContentLength());
        assertNotNull(response.getBody());
        assertEquals(9L, response.getBody().contentLength());
    }

    @Test
    public void downloadUsesTheCsvContentType() throws Exception {
        File file = tempFolder.newFile("usage.csv");
        Files.write(file.toPath(), "a,b\n1,2\n".getBytes("UTF-8"));
        Report completed = report(13L, ReportStatus.COMPLETED, ReportType.CSV);
        completed.setFilePath(file.getAbsolutePath());
        when(reportService.getReport(13L)).thenReturn(Optional.of(completed));

        ResponseEntity<Resource> response = controller.downloadReport(13L);

        assertEquals("text/csv", response.getHeaders().getContentType().toString());
    }

    @Test
    public void downloadUsesTheExcelContentType() throws Exception {
        File file = tempFolder.newFile("usage.xlsx");
        Files.write(file.toPath(), "xlsx".getBytes("UTF-8"));
        Report completed = report(14L, ReportStatus.COMPLETED, ReportType.EXCEL);
        completed.setFilePath(file.getAbsolutePath());
        when(reportService.getReport(14L)).thenReturn(Optional.of(completed));

        ResponseEntity<Resource> response = controller.downloadReport(14L);

        assertEquals("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                response.getHeaders().getContentType().toString());
    }

    @Test
    public void deleteReportReturns204WhenTheReportExisted() {
        when(reportService.deleteReport(16L)).thenReturn(true);

        assertEquals(HttpStatus.NO_CONTENT, controller.deleteReport(16L).getStatusCode());
    }

    @Test
    public void deleteReportReturns404WhenTheReportDidNotExist() {
        when(reportService.deleteReport(404L)).thenReturn(false);

        assertEquals(HttpStatus.NOT_FOUND, controller.deleteReport(404L).getStatusCode());
    }

    @Test
    public void downloadRejectsADirectoryMasqueradingAsAReportFile() throws Exception {
        File dir = tempFolder.newFolder("as-file");
        Report completed = report(17L, ReportStatus.COMPLETED, ReportType.CSV);
        completed.setFilePath(dir.getAbsolutePath());
        when(reportService.getReport(17L)).thenReturn(Optional.of(completed));

        ResponseEntity<Resource> response = controller.downloadReport(17L);

        assertEquals(HttpStatus.NOT_FOUND, response.getStatusCode());
        assertTrue(dir.exists());
    }
}
