package com.otterworks.report.model;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.time.Instant;
import java.util.Map;

@Schema(description = "Request to generate a new report")
public record ReportRequest(
        @NotBlank(message = "Report name is required")
        @Schema(description = "Human-readable name for the report", requiredMode = Schema.RequiredMode.REQUIRED,
                example = "Monthly Usage Report")
        String reportName,

        @NotNull(message = "Report category is required")
        @Schema(description = "Category of data to include", requiredMode = Schema.RequiredMode.REQUIRED)
        ReportCategory category,

        @NotNull(message = "Report type is required")
        @Schema(description = "Output format", requiredMode = Schema.RequiredMode.REQUIRED, example = "PDF")
        ReportType reportType,

        @NotBlank(message = "Requester ID is required")
        @Schema(description = "User ID requesting the report", requiredMode = Schema.RequiredMode.REQUIRED)
        String requestedBy,

        @Schema(description = "Start of reporting period")
        Instant dateFrom,

        @Schema(description = "End of reporting period")
        Instant dateTo,

        @Schema(description = "Additional parameters for report generation")
        Map<String, String> parameters) {
}
