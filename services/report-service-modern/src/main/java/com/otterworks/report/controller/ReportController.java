package com.otterworks.report.controller;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportResponse;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.service.ReportService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/reports")
@Tag(name = "Reports", description = "Report generation and management")
public class ReportController {

    private static final Logger logger = LoggerFactory.getLogger(ReportController.class);

    private final ReportService reportService;

    public ReportController(ReportService reportService) {
        this.reportService = reportService;
    }

    @PostMapping
    @Operation(summary = "Create a new report",
            description = "Submits a report generation request. The report is generated asynchronously.")
    @ApiResponse(responseCode = "202", description = "Report request accepted")
    @ApiResponse(responseCode = "400", description = "Invalid request")
    public ResponseEntity<ReportResponse> createReport(@Valid @RequestBody ReportRequest request) {
        logger.info("Report request: name={}, category={}, type={}, by={}",
                request.reportName(), request.category(), request.reportType(), request.requestedBy());
        Report report = reportService.createReport(request);
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(ReportResponse.fromEntity(report));
    }

    @GetMapping("/{id}")
    @Operation(summary = "Get report by ID", description = "Returns the report metadata and status")
    @ApiResponse(responseCode = "200", description = "Report found")
    @ApiResponse(responseCode = "404", description = "Report not found")
    public ResponseEntity<ReportResponse> getReport(@Parameter(description = "Report ID") @PathVariable Long id) {
        return reportService.getReport(id)
                .map(ReportResponse::fromEntity)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @GetMapping
    @Operation(summary = "List reports", description = "List reports filtered by user ID or status")
    public ResponseEntity<Map<String, Object>> listReports(
            @Parameter(description = "Filter by user ID") @RequestParam(required = false) String userId,
            @Parameter(description = "Filter by status") @RequestParam(required = false) ReportStatus status) {
        List<Report> reports;
        if (userId != null) {
            reports = reportService.getReportsByUser(userId);
        } else if (status != null) {
            reports = reportService.getReportsByStatus(status);
        } else {
            reports = reportService.getReportsByStatus(ReportStatus.COMPLETED);
        }
        List<ReportResponse> responses = reports.stream().map(ReportResponse::fromEntity).toList();
        Map<String, Object> body = new HashMap<>();
        body.put("reports", responses);
        body.put("total", responses.size());
        return ResponseEntity.ok(body);
    }

    @GetMapping("/{id}/download")
    @Operation(summary = "Download a generated report", description = "Returns the report file for download")
    @ApiResponse(responseCode = "200", description = "Report file")
    @ApiResponse(responseCode = "404", description = "Report not found or not yet completed")
    @ApiResponse(responseCode = "409", description = "Report is still generating")
    public ResponseEntity<Resource> downloadReport(@Parameter(description = "Report ID") @PathVariable Long id) {
        Report report = reportService.getReport(id).orElse(null);
        if (report == null) {
            return ResponseEntity.notFound().build();
        }
        if (report.getStatus() == ReportStatus.GENERATING || report.getStatus() == ReportStatus.PENDING) {
            return ResponseEntity.status(HttpStatus.CONFLICT).build();
        }
        if (report.getStatus() == ReportStatus.FAILED || report.getFilePath() == null) {
            return ResponseEntity.notFound().build();
        }

        Path file = Path.of(report.getFilePath());
        if (!Files.isRegularFile(file)) {
            logger.warn("Report file missing: {}", report.getFilePath());
            return ResponseEntity.notFound().build();
        }
        try {
            long size = Files.size(file);
            return ResponseEntity.ok()
                    .contentType(MediaType.parseMediaType(contentType(report.getReportType())))
                    .header(HttpHeaders.CONTENT_DISPOSITION,
                            "attachment; filename=\"" + file.getFileName() + "\"")
                    .contentLength(size)
                    .body(new FileSystemResource(file));
        } catch (IOException e) {
            logger.error("Failed to read report file {}: {}", report.getFilePath(), e.getMessage());
            return ResponseEntity.notFound().build();
        }
    }

    @DeleteMapping("/{id}")
    @Operation(summary = "Delete a report", description = "Deletes the report record and its generated file")
    @ApiResponse(responseCode = "204", description = "Report deleted")
    @ApiResponse(responseCode = "404", description = "Report not found")
    public ResponseEntity<Void> deleteReport(@Parameter(description = "Report ID") @PathVariable Long id) {
        return reportService.deleteReport(id)
                ? ResponseEntity.noContent().build()
                : ResponseEntity.notFound().build();
    }

    static String contentType(ReportType reportType) {
        return switch (reportType) {
            case PDF -> "application/pdf";
            case CSV -> "text/csv";
            case EXCEL -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
        };
    }
}
