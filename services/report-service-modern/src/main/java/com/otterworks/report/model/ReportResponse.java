package com.otterworks.report.model;

import io.swagger.v3.oas.annotations.media.Schema;

import java.time.Instant;

@Schema(description = "Report metadata response")
public record ReportResponse(
        @Schema(description = "Report ID") Long id,
        @Schema(description = "Report name") String reportName,
        @Schema(description = "Report category") String category,
        @Schema(description = "Output format") String reportType,
        @Schema(description = "Generation status") String status,
        @Schema(description = "Who requested it") String requestedBy,
        @Schema(description = "Data start date") Instant dateFrom,
        @Schema(description = "Data end date") Instant dateTo,
        @Schema(description = "Request timestamp") Instant createdAt,
        @Schema(description = "Completion timestamp") Instant completedAt,
        @Schema(description = "File size in bytes") Long fileSizeBytes,
        @Schema(description = "Number of rows") Integer rowCount,
        @Schema(description = "Download URL") String downloadUrl,
        @Schema(description = "Error message if failed") String errorMessage) {

    public static ReportResponse fromEntity(Report report) {
        return new ReportResponse(
                report.getId(),
                report.getReportName(),
                nameOf(report.getCategory()),
                nameOf(report.getReportType()),
                nameOf(report.getStatus()),
                report.getRequestedBy(),
                report.getDateFrom(),
                report.getDateTo(),
                report.getCreatedAt(),
                report.getCompletedAt(),
                report.getFileSizeBytes(),
                report.getRowCount(),
                report.getFilePath() != null ? "/api/v1/reports/" + report.getId() + "/download" : null,
                report.getErrorMessage());
    }

    private static String nameOf(Enum<?> value) {
        return value != null ? value.name() : null;
    }
}
