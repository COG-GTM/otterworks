package com.otterworks.report.model;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;

import java.util.Date;

/**
 * Response DTO for report metadata.
 *
 * LEGACY: Uses mutable POJO pattern. Modern Java would use a record.
 */
@ApiModel(description = "Report metadata response")
public class ReportResponse {

    @ApiModelProperty(value = "Report ID")
    private Long id;

    @ApiModelProperty(value = "Report name")
    private String reportName;

    @ApiModelProperty(value = "Report category")
    private String category;

    @ApiModelProperty(value = "Output format")
    private String reportType;

    @ApiModelProperty(value = "Generation status")
    private String status;

    @ApiModelProperty(value = "Who requested it")
    private String requestedBy;

    @ApiModelProperty(value = "Data start date")
    private Date dateFrom;

    @ApiModelProperty(value = "Data end date")
    private Date dateTo;

    @ApiModelProperty(value = "Request timestamp")
    private Date createdAt;

    @ApiModelProperty(value = "Completion timestamp")
    private Date completedAt;

    @ApiModelProperty(value = "File size in bytes")
    private Long fileSizeBytes;

    @ApiModelProperty(value = "Number of rows")
    private Integer rowCount;

    @ApiModelProperty(value = "Download URL")
    private String downloadUrl;

    @ApiModelProperty(value = "Generic error message if failed")
    private String errorMessage;

    @ApiModelProperty(value = "Failure reason code if failed",
            allowableValues = "DATA_SOURCE_UNAVAILABLE, INVALID_PARAMETERS, GENERATION_FAILED")
    private String failureReason;

    public ReportResponse() {
    }

    // LEGACY: Static factory method with manual field mapping
    // Modern approach: MapStruct or record constructor
    public static ReportResponse fromEntity(Report report) {
        ReportResponse response = new ReportResponse();
        response.setId(report.getId());
        response.setReportName(report.getReportName());
        response.setCategory(report.getCategory() != null ? report.getCategory().name() : null);
        response.setReportType(report.getReportType() != null ? report.getReportType().name() : null);
        response.setStatus(report.getStatus() != null ? report.getStatus().name() : null);
        response.setRequestedBy(report.getRequestedBy());
        response.setDateFrom(report.getDateFrom());
        response.setDateTo(report.getDateTo());
        response.setCreatedAt(report.getCreatedAt());
        response.setCompletedAt(report.getCompletedAt());
        response.setFileSizeBytes(report.getFileSizeBytes());
        response.setRowCount(report.getRowCount());
        if (report.getFilePath() != null) {
            response.setDownloadUrl("/api/v1/reports/" + report.getId() + "/download");
        }
        ReportFailureReason failureReason = ReportFailureReason.fromStoredValue(report.getErrorMessage());
        if (failureReason != null) {
            response.setFailureReason(failureReason.name());
            response.setErrorMessage(failureReason.getMessage());
        }
        return response;
    }

    // Getters and setters
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

    public String getCategory() {
        return category;
    }

    public void setCategory(String category) {
        this.category = category;
    }

    public String getReportType() {
        return reportType;
    }

    public void setReportType(String reportType) {
        this.reportType = reportType;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
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

    public String getDownloadUrl() {
        return downloadUrl;
    }

    public void setDownloadUrl(String downloadUrl) {
        this.downloadUrl = downloadUrl;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public void setErrorMessage(String errorMessage) {
        this.errorMessage = errorMessage;
    }

    public String getFailureReason() {
        return failureReason;
    }

    public void setFailureReason(String failureReason) {
        this.failureReason = failureReason;
    }
}
