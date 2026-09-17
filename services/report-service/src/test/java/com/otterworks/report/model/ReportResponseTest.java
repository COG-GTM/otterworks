package com.otterworks.report.model;

import org.junit.Test;

import java.util.Date;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

/**
 * Unit tests for the {@link ReportResponse} DTO and its entity mapping.
 */
public class ReportResponseTest {

    private static final Date CREATED_AT = new Date(1_704_067_200_000L); // 2024-01-01T00:00:00Z
    private static final Date COMPLETED_AT = new Date(1_704_067_260_000L);

    @Test
    public void fromEntityCopiesEveryExposedField() {
        Report report = new Report();
        report.setId(3L);
        report.setReportName("Usage");
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(ReportType.CSV);
        report.setStatus(ReportStatus.COMPLETED);
        report.setRequestedBy("user-3");
        report.setDateFrom(CREATED_AT);
        report.setDateTo(COMPLETED_AT);
        report.setCreatedAt(CREATED_AT);
        report.setCompletedAt(COMPLETED_AT);
        report.setFileSizeBytes(512L);
        report.setRowCount(42);
        report.setFilePath("/tmp/reports/usage.csv");
        report.setErrorMessage("none");

        ReportResponse response = ReportResponse.fromEntity(report);

        assertEquals(Long.valueOf(3L), response.getId());
        assertEquals("Usage", response.getReportName());
        assertEquals("USAGE_ANALYTICS", response.getCategory());
        assertEquals("CSV", response.getReportType());
        assertEquals("COMPLETED", response.getStatus());
        assertEquals("user-3", response.getRequestedBy());
        assertEquals(CREATED_AT, response.getDateFrom());
        assertEquals(COMPLETED_AT, response.getDateTo());
        assertEquals(CREATED_AT, response.getCreatedAt());
        assertEquals(COMPLETED_AT, response.getCompletedAt());
        assertEquals(Long.valueOf(512L), response.getFileSizeBytes());
        assertEquals(Integer.valueOf(42), response.getRowCount());
        assertEquals("/api/v1/reports/3/download", response.getDownloadUrl());
        assertEquals("none", response.getErrorMessage());
    }

    @Test
    public void fromEntityLeavesEnumStringsNullWhenTheEntityHasNoEnums() {
        Report report = new Report();
        report.setId(4L);
        report.setReportName("Draft");

        ReportResponse response = ReportResponse.fromEntity(report);

        assertNull(response.getCategory());
        assertNull(response.getReportType());
        assertNull(response.getStatus());
        assertNull("no file path means no download URL", response.getDownloadUrl());
        assertNull(response.getErrorMessage());
    }

    @Test
    public void fromEntityOnlyPublishesADownloadUrlOnceAFileExists() {
        Report report = new Report();
        report.setId(5L);
        report.setStatus(ReportStatus.GENERATING);

        assertNull(ReportResponse.fromEntity(report).getDownloadUrl());

        report.setFilePath("/tmp/reports/5.pdf");
        assertEquals("/api/v1/reports/5/download", ReportResponse.fromEntity(report).getDownloadUrl());
    }

    @Test
    public void everyFieldRoundTripsThroughItsAccessors() {
        ReportResponse response = new ReportResponse();

        response.setId(6L);
        response.setReportName("Compliance");
        response.setCategory("COMPLIANCE");
        response.setReportType("PDF");
        response.setStatus("FAILED");
        response.setRequestedBy("user-6");
        response.setDateFrom(CREATED_AT);
        response.setDateTo(COMPLETED_AT);
        response.setCreatedAt(CREATED_AT);
        response.setCompletedAt(COMPLETED_AT);
        response.setFileSizeBytes(1L);
        response.setRowCount(0);
        response.setDownloadUrl("/api/v1/reports/6/download");
        response.setErrorMessage("boom");

        assertEquals(Long.valueOf(6L), response.getId());
        assertEquals("Compliance", response.getReportName());
        assertEquals("COMPLIANCE", response.getCategory());
        assertEquals("PDF", response.getReportType());
        assertEquals("FAILED", response.getStatus());
        assertEquals("user-6", response.getRequestedBy());
        assertEquals(CREATED_AT, response.getDateFrom());
        assertEquals(COMPLETED_AT, response.getDateTo());
        assertEquals(CREATED_AT, response.getCreatedAt());
        assertEquals(COMPLETED_AT, response.getCompletedAt());
        assertEquals(Long.valueOf(1L), response.getFileSizeBytes());
        assertEquals(Integer.valueOf(0), response.getRowCount());
        assertEquals("/api/v1/reports/6/download", response.getDownloadUrl());
        assertEquals("boom", response.getErrorMessage());
    }
}
