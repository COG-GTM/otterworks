package com.otterworks.report.controller;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportResponse;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.security.AuthenticatedUser;
import com.otterworks.report.service.ReportService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import io.swagger.annotations.ApiResponse;
import io.swagger.annotations.ApiResponses;
import org.apache.commons.io.FileUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import javax.validation.Valid;
import java.io.File;
import java.io.IOException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

/**
 * REST controller for report management.
 *
 * LEGACY PATTERNS:
 * - SpringFox @Api / @ApiOperation / @ApiResponse annotations
 *   (target: springdoc @Tag / @Operation / @ApiResponse from io.swagger.v3)
 * - javax.validation.Valid (target: jakarta.validation.Valid)
 * - Commons IO FileUtils for file reading (target: Files.readAllBytes or streaming)
 * - ByteArrayResource loads entire file into memory (target: InputStreamResource for streaming)
 * - No pagination on list endpoint
 * - Manual response mapping without MapStruct or similar
 *
 * Every endpoint is scoped to the authenticated caller: reports are created for the
 * caller, and only their owner (or an ADMIN) can see, download or delete them.
 * Reports owned by someone else answer 404 so IDs cannot be probed for existence.
 */
@RestController
@RequestMapping("/api/v1/reports")
@Api(tags = "Reports", description = "Report generation and management")
public class ReportController {

    private static final Logger logger = LoggerFactory.getLogger(ReportController.class);

    private final ReportService reportService;

    public ReportController(ReportService reportService) {
        this.reportService = reportService;
    }

    @PostMapping
    @ApiOperation(value = "Create a new report", notes = "Submits a report generation request. The report is generated asynchronously.")
    @ApiResponses({
            @ApiResponse(code = 202, message = "Report request accepted"),
            @ApiResponse(code = 400, message = "Invalid request")
    })
    public ResponseEntity<ReportResponse> createReport(
            @AuthenticationPrincipal AuthenticatedUser caller,
            @Valid @RequestBody ReportRequest request) {

        logger.info("Report request: name={}, category={}, type={}, by={}",
                request.getReportName(), request.getCategory(),
                request.getReportType(), caller.getUserId());

        Report report = reportService.createReport(request, caller.getUserId());
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .body(ReportResponse.fromEntity(report));
    }

    @GetMapping("/{id}")
    @ApiOperation(value = "Get report by ID", notes = "Returns the report metadata and status")
    @ApiResponses({
            @ApiResponse(code = 200, message = "Report found"),
            @ApiResponse(code = 404, message = "Report not found")
    })
    public ResponseEntity<ReportResponse> getReport(
            @AuthenticationPrincipal AuthenticatedUser caller,
            @ApiParam(value = "Report ID", required = true)
            @PathVariable Long id) {

        Optional<Report> report = findAccessibleReport(id, caller);
        if (!report.isPresent()) { // LEGACY: !isPresent() instead of isEmpty()
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(ReportResponse.fromEntity(report.get()));
    }

    @GetMapping
    @ApiOperation(value = "List reports",
            notes = "Lists the caller's reports, optionally filtered by status. Only admins may list another user's reports or all reports.")
    @ApiResponses({
            @ApiResponse(code = 200, message = "Reports"),
            @ApiResponse(code = 403, message = "userId names another user and the caller is not an admin")
    })
    public ResponseEntity<Map<String, Object>> listReports(
            @AuthenticationPrincipal AuthenticatedUser caller,
            @ApiParam(value = "Filter by user ID (admins only, unless it is the caller's own ID)")
            @RequestParam(required = false) String userId,
            @ApiParam(value = "Filter by status")
            @RequestParam(required = false) ReportStatus status) {

        if (userId != null && !caller.owns(userId) && !caller.isAdmin()) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        }

        List<Report> reports;
        if (userId != null || !caller.isAdmin()) {
            String owner = userId != null ? userId : caller.getUserId();
            reports = reportService.getReportsByUser(owner);
            if (status != null) {
                reports = reports.stream()
                        .filter(report -> report.getStatus() == status)
                        .collect(Collectors.toList());
            }
        } else if (status != null) {
            reports = reportService.getReportsByStatus(status);
        } else {
            reports = reportService.getReportsByStatus(ReportStatus.COMPLETED);
        }

        List<ReportResponse> responses = reports.stream()
                .map(ReportResponse::fromEntity)
                .collect(Collectors.toList()); // LEGACY: .toList() available in Java 16+

        // LEGACY: Manual response wrapper instead of a proper Page/Slice object
        Map<String, Object> response = new HashMap<>();
        response.put("reports", responses);
        response.put("total", responses.size());

        return ResponseEntity.ok(response);
    }

    @GetMapping("/{id}/download")
    @ApiOperation(value = "Download a generated report", notes = "Returns the report file for download")
    @ApiResponses({
            @ApiResponse(code = 200, message = "Report file"),
            @ApiResponse(code = 404, message = "Report not found or not yet completed"),
            @ApiResponse(code = 409, message = "Report is still generating")
    })
    public ResponseEntity<Resource> downloadReport(
            @AuthenticationPrincipal AuthenticatedUser caller,
            @ApiParam(value = "Report ID", required = true)
            @PathVariable Long id) {

        Optional<Report> optReport = findAccessibleReport(id, caller);
        if (!optReport.isPresent()) {
            return ResponseEntity.notFound().build();
        }

        Report report = optReport.get();

        if (report.getStatus() == ReportStatus.GENERATING || report.getStatus() == ReportStatus.PENDING) {
            return ResponseEntity.status(HttpStatus.CONFLICT).build();
        }

        if (report.getStatus() == ReportStatus.FAILED || report.getFilePath() == null) {
            return ResponseEntity.notFound().build();
        }

        File file = new File(report.getFilePath());
        if (!file.exists()) {
            logger.warn("Report file missing: {}", report.getFilePath());
            return ResponseEntity.notFound().build();
        }

        try {
            // LEGACY: Commons IO FileUtils.readFileToByteArray loads entire file into memory
            // Modern approach: InputStreamResource with streaming, or S3 presigned URL
            byte[] fileContent = FileUtils.readFileToByteArray(file);
            ByteArrayResource resource = new ByteArrayResource(fileContent);

            String contentType = getContentType(report.getReportType());
            String fileName = file.getName();

            return ResponseEntity.ok()
                    .contentType(MediaType.parseMediaType(contentType))
                    .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + fileName + "\"")
                    .contentLength(fileContent.length)
                    .body(resource);

        } catch (IOException e) {
            logger.error("Failed to read report file {}: {}", report.getFilePath(), e.getMessage());
            return ResponseEntity.notFound().build();
        }
    }

    @DeleteMapping("/{id}")
    @ApiOperation(value = "Delete a report", notes = "Deletes the report record and its generated file")
    @ApiResponses({
            @ApiResponse(code = 204, message = "Report deleted"),
            @ApiResponse(code = 404, message = "Report not found")
    })
    public ResponseEntity<Void> deleteReport(
            @AuthenticationPrincipal AuthenticatedUser caller,
            @ApiParam(value = "Report ID", required = true)
            @PathVariable Long id) {

        boolean deleted = reportService.deleteReport(id, report -> canAccess(caller, report));
        if (!deleted) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.noContent().build();
    }

    // ----- Private helpers -----

    private Optional<Report> findAccessibleReport(Long id, AuthenticatedUser caller) {
        return reportService.getReport(id).filter(report -> canAccess(caller, report));
    }

    private static boolean canAccess(AuthenticatedUser caller, Report report) {
        return caller.isAdmin() || caller.owns(report.getRequestedBy());
    }

    private String getContentType(com.otterworks.report.model.ReportType reportType) {
        // LEGACY: switch without enhanced syntax
        switch (reportType) {
            case PDF:
                return "application/pdf";
            case CSV:
                return "text/csv";
            case EXCEL:
                return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
            default:
                return "application/octet-stream";
        }
    }
}
