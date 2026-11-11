package com.otterworks.report.model;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.EnumType;
import javax.persistence.Enumerated;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.Lob;
import javax.persistence.Table;
import javax.persistence.Temporal;
import javax.persistence.TemporalType;
import javax.validation.constraints.NotNull;
import java.util.Date;

/**
 * JPA entity representing a generated report.
 *
 * LEGACY PATTERNS:
 * - javax.persistence.* (target: jakarta.persistence.*)
 * - javax.validation.* (target: jakarta.validation.*)
 * - java.util.Date fields (target: java.time.Instant / LocalDateTime)
 * - SpringFox @ApiModel / @ApiModelProperty (target: @Schema from springdoc)
 * - No Lombok — uses manual getters/setters (verbose but explicit)
 */
@Entity
@Table(name = "reports")
@ApiModel(description = "Generated report metadata")
public class Report {

    public static final String GENERATION_FAILED_MESSAGE = "Report generation failed";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @ApiModelProperty(value = "Unique report identifier", readOnly = true)
    private Long id;

    @NotNull
    @Column(name = "report_name", nullable = false)
    @ApiModelProperty(value = "Human-readable report name", required = true)
    private String reportName;

    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(name = "category", nullable = false)
    @ApiModelProperty(value = "Report category", required = true)
    private ReportCategory category;

    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(name = "report_type", nullable = false)
    @ApiModelProperty(value = "Output format: PDF, CSV, or EXCEL", required = true)
    private ReportType reportType;

    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false)
    @ApiModelProperty(value = "Current generation status", readOnly = true)
    private ReportStatus status;

    @Column(name = "requested_by", nullable = false)
    @ApiModelProperty(value = "User ID who requested the report")
    private String requestedBy;

    // LEGACY: java.util.Date instead of java.time.Instant
    @Temporal(TemporalType.TIMESTAMP)
    @Column(name = "date_from")
    @ApiModelProperty(value = "Report data start date")
    private Date dateFrom;

    // LEGACY: java.util.Date instead of java.time.Instant
    @Temporal(TemporalType.TIMESTAMP)
    @Column(name = "date_to")
    @ApiModelProperty(value = "Report data end date")
    private Date dateTo;

    // LEGACY: java.util.Date instead of java.time.Instant
    @Temporal(TemporalType.TIMESTAMP)
    @Column(name = "created_at", nullable = false)
    @ApiModelProperty(value = "When the report was requested", readOnly = true)
    private Date createdAt;

    // LEGACY: java.util.Date instead of java.time.Instant
    @Temporal(TemporalType.TIMESTAMP)
    @Column(name = "completed_at")
    @ApiModelProperty(value = "When the report finished generating", readOnly = true)
    private Date completedAt;

    @Column(name = "file_path")
    @ApiModelProperty(value = "Path to the generated report file")
    private String filePath;

    @Column(name = "file_size_bytes")
    @ApiModelProperty(value = "Size of the generated file in bytes")
    private Long fileSizeBytes;

    @Column(name = "row_count")
    @ApiModelProperty(value = "Number of data rows in the report")
    private Integer rowCount;

    @Lob
    @Column(name = "error_message")
    @ApiModelProperty(value = "Error message if generation failed")
    private String errorMessage;

    @Column(name = "parameters")
    @ApiModelProperty(value = "JSON-encoded report parameters")
    private String parameters;

    // Default constructor required by JPA
    public Report() {
    }

    // LEGACY: Manual getters and setters (verbose Java 8 style)
    // Modern approach would use records (Java 16+) or Lombok

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getReportName() {
        return reportName;
    }

    public void setReportName(String reportName) {
        this.reportName = reportName;
    }

    public ReportCategory getCategory() {
        return category;
    }

    public void setCategory(ReportCategory category) {
        this.category = category;
    }

    public ReportType getReportType() {
        return reportType;
    }

    public void setReportType(ReportType reportType) {
        this.reportType = reportType;
    }

    public ReportStatus getStatus() {
        return status;
    }

    public void setStatus(ReportStatus status) {
        this.status = status;
    }

    public String getRequestedBy() {
        return requestedBy;
    }

    public void setRequestedBy(String requestedBy) {
        this.requestedBy = requestedBy;
    }

    public Date getDateFrom() {
        return dateFrom;
    }

    public void setDateFrom(Date dateFrom) {
        this.dateFrom = dateFrom;
    }

    public Date getDateTo() {
        return dateTo;
    }

    public void setDateTo(Date dateTo) {
        this.dateTo = dateTo;
    }

    public Date getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Date createdAt) {
        this.createdAt = createdAt;
    }

    public Date getCompletedAt() {
        return completedAt;
    }

    public void setCompletedAt(Date completedAt) {
        this.completedAt = completedAt;
    }

    public String getFilePath() {
        return filePath;
    }

    public void setFilePath(String filePath) {
        this.filePath = filePath;
    }

    public Long getFileSizeBytes() {
        return fileSizeBytes;
    }

    public void setFileSizeBytes(Long fileSizeBytes) {
        this.fileSizeBytes = fileSizeBytes;
    }

    public Integer getRowCount() {
        return rowCount;
    }

    public void setRowCount(Integer rowCount) {
        this.rowCount = rowCount;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public void setErrorMessage(String errorMessage) {
        this.errorMessage = errorMessage;
    }

    public String getParameters() {
        return parameters;
    }

    public void setParameters(String parameters) {
        this.parameters = parameters;
    }

    // LEGACY: toString() with string concatenation instead of String.format or records
    @Override
    public String toString() {
        return "Report{" +
                "id=" + id +
                ", reportName='" + reportName + '\'' +
                ", category=" + category +
                ", reportType=" + reportType +
                ", status=" + status +
                ", requestedBy='" + requestedBy + '\'' +
                ", createdAt=" + createdAt +
                '}';
    }
}
