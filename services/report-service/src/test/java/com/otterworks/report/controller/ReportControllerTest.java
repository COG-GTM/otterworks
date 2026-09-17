package com.otterworks.report.controller;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportResponse;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.service.ReportService;
import org.apache.commons.io.FileUtils;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.io.File;
import java.util.Arrays;
import java.util.Collections;
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
 * Unit tests for {@link ReportController} against a mocked {@link ReportService}.
 *
 * The existing {@code ReportControllerIntegrationTest} drives the happy paths through MockMvc;
 * these tests cover the status/HTTP mapping of the download endpoint and the filter branches of
 * the list endpoint, which the integration test does not reach.
 */
@RunWith(MockitoJUnitRunner.class)
public class ReportControllerTest {

    @Rule
    public TemporaryFolder tempFolder = new TemporaryFolder();

    @Mock
    private ReportService reportService;

    private ReportController controller;

    @Before
    public void setUp() {
        controller = new ReportController(reportService);
    }

    @Test
    public void createReportAcceptsTheRequestAndEchoesTheStoredReport() {
        ReportRequest request = new ReportRequest();
        request.setReportName("Monthly Usage");
        request.setCategory(ReportCategory.USAGE_ANALYTICS);
        request.setReportType(ReportType.PDF);
        request.setRequestedBy("user-1");
        Report stored = report(1L, ReportStatus.PENDING, ReportType.PDF, null);
        when(reportService.createReport(request)).thenReturn(stored);

        ResponseEntity<ReportResponse> response = controller.createReport(request);

        assertEquals(HttpStatus.ACCEPTED, response.getStatusCode());
        assertNotNull(response.getBody());
        assertEquals(Long.valueOf(1L), response.getBody().getId());
        assertEquals("PENDING", response.getBody().getStatus());
    }

    @Test
    public void getReportReturnsTheReportWhenItExists() {
        when(reportService.getReport(2L))
                .thenReturn(Optional.of(report(2L, ReportStatus.COMPLETED, ReportType.CSV, "/tmp/r2.csv")));

        ResponseEntity<ReportResponse> response = controller.getReport(2L);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("/api/v1/reports/2/download", response.getBody().getDownloadUrl());
    }

    @Test
    public void getReportReturns404ForAnUnknownId() {
        when(reportService.getReport(404L)).thenReturn(Optional.<Report>empty());

        ResponseEntity<ReportResponse> response = controller.getReport(404L);

        assertEquals(HttpStatus.NOT_FOUND, response.getStatusCode());
        assertNull(response.getBody());
    }

    @Test
    public void listReportsFiltersByUserIdWhenSupplied() {
        List<Report> reports = Arrays.asList(
                report(1L, ReportStatus.COMPLETED, ReportType.CSV, null),
                report(2L, ReportStatus.FAILED, ReportType.PDF, null));
        when(reportService.getReportsByUser("user-1")).thenReturn(reports);

        Map<String, Object> body = controller.listReports("user-1", null).getBody();

        assertEquals(2, body.get("total"));
        assertEquals(2, ((List<?>) body.get("reports")).size());
        verify(reportService).getReportsByUser("user-1");
    }

    @Test
    public void listReportsFiltersByStatusWhenNoUserIdIsSupplied() {
        when(reportService.getReportsByStatus(ReportStatus.FAILED))
                .thenReturn(Collections.singletonList(report(3L, ReportStatus.FAILED, ReportType.CSV, null)));

        Map<String, Object> body = controller.listReports(null, ReportStatus.FAILED).getBody();

        assertEquals(1, body.get("total"));
    }

    @Test
    public void listReportsDefaultsToCompletedReports() {
        when(reportService.getReportsByStatus(ReportStatus.COMPLETED))
                .thenReturn(Collections.<Report>emptyList());

        Map<String, Object> body = controller.listReports(null, null).getBody();

        assertEquals(0, body.get("total"));
        assertTrue(((List<?>) body.get("reports")).isEmpty());
        verify(reportService).getReportsByStatus(ReportStatus.COMPLETED);
    }

    @Test
    public void downloadReturns404ForAnUnknownId() {
        when(reportService.getReport(404L)).thenReturn(Optional.<Report>empty());

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(404L).getStatusCode());
    }

    @Test
    public void downloadReturns409WhileTheReportIsStillBeingGenerated() {
        when(reportService.getReport(5L))
                .thenReturn(Optional.of(report(5L, ReportStatus.GENERATING, ReportType.CSV, null)));
        when(reportService.getReport(6L))
                .thenReturn(Optional.of(report(6L, ReportStatus.PENDING, ReportType.CSV, null)));

        assertEquals(HttpStatus.CONFLICT, controller.downloadReport(5L).getStatusCode());
        assertEquals(HttpStatus.CONFLICT, controller.downloadReport(6L).getStatusCode());
    }

    @Test
    public void downloadReturns404ForAFailedReport() {
        when(reportService.getReport(7L))
                .thenReturn(Optional.of(report(7L, ReportStatus.FAILED, ReportType.CSV, "/tmp/whatever.csv")));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(7L).getStatusCode());
    }

    @Test
    public void downloadReturns404WhenTheReportHasNoFilePath() {
        when(reportService.getReport(8L))
                .thenReturn(Optional.of(report(8L, ReportStatus.COMPLETED, ReportType.CSV, null)));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(8L).getStatusCode());
    }

    @Test
    public void downloadReturns404WhenTheFileHasBeenRemovedFromDisk() {
        String missing = tempFolder.getRoot().getAbsolutePath() + "/gone.csv";
        when(reportService.getReport(9L))
                .thenReturn(Optional.of(report(9L, ReportStatus.COMPLETED, ReportType.CSV, missing)));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(9L).getStatusCode());
    }

    @Test
    public void downloadReturns404WhenTheFileCannotBeRead() throws Exception {
        // A directory at the recorded path exists but cannot be read as a file.
        File directory = tempFolder.newFolder("not-a-file.csv");
        when(reportService.getReport(10L)).thenReturn(Optional.of(
                report(10L, ReportStatus.COMPLETED, ReportType.CSV, directory.getAbsolutePath())));

        assertEquals(HttpStatus.NOT_FOUND, controller.downloadReport(10L).getStatusCode());
    }

    @Test
    public void downloadStreamsACsvReportAsAnAttachment() throws Exception {
        File file = tempFolder.newFile("usage.csv");
        FileUtils.writeStringToFile(file, "id,name\n1,otter\n", "UTF-8");
        when(reportService.getReport(11L)).thenReturn(Optional.of(
                report(11L, ReportStatus.COMPLETED, ReportType.CSV, file.getAbsolutePath())));

        ResponseEntity<Resource> response = controller.downloadReport(11L);

        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals("text/csv", response.getHeaders().getContentType().toString());
        assertEquals("attachment; filename=\"usage.csv\"",
                response.getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION));
        assertEquals(file.length(), response.getHeaders().getContentLength());
        assertEquals(file.length(), response.getBody().contentLength());
    }

    @Test
    public void downloadUsesThePdfContentType() throws Exception {
        File file = tempFolder.newFile("usage.pdf");
        FileUtils.writeStringToFile(file, "%PDF-1.4", "UTF-8");
        when(reportService.getReport(12L)).thenReturn(Optional.of(
                report(12L, ReportStatus.COMPLETED, ReportType.PDF, file.getAbsolutePath())));

        assertEquals("application/pdf",
                controller.downloadReport(12L).getHeaders().getContentType().toString());
    }

    @Test
    public void downloadUsesTheSpreadsheetContentType() throws Exception {
        File file = tempFolder.newFile("usage.xlsx");
        FileUtils.writeStringToFile(file, "PK", "UTF-8");
        when(reportService.getReport(13L)).thenReturn(Optional.of(
                report(13L, ReportStatus.COMPLETED, ReportType.EXCEL, file.getAbsolutePath())));

        assertEquals("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                controller.downloadReport(13L).getHeaders().getContentType().toString());
    }

    @Test
    public void deleteReturns204WhenTheReportWasRemoved() {
        when(reportService.deleteReport(14L)).thenReturn(true);

        assertEquals(HttpStatus.NO_CONTENT, controller.deleteReport(14L).getStatusCode());
    }

    @Test
    public void deleteReturns404WhenThereWasNothingToRemove() {
        when(reportService.deleteReport(404L)).thenReturn(false);

        assertEquals(HttpStatus.NOT_FOUND, controller.deleteReport(404L).getStatusCode());
    }

    // ----- helpers -----

    private static Report report(Long id, ReportStatus status, ReportType type, String filePath) {
        Report report = new Report();
        report.setId(id);
        report.setReportName("Report " + id);
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(type);
        report.setStatus(status);
        report.setRequestedBy("user-1");
        report.setFilePath(filePath);
        return report;
    }
}
