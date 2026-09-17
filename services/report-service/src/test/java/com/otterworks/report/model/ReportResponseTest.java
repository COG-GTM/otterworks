package com.otterworks.report.model;

import org.junit.Test;

import java.util.Date;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

/**
 * Unit tests for the {@link ReportResponse} DTO mapping.
 */
public class ReportResponseTest {

    private static final Date FROM = new Date(1_704_067_200_000L); // 2024-01-01T00:00:00Z
    private static final Date TO = new Date(1_706_745_600_000L);   // 2024-02-01T00:00:00Z

    @Test
    public void fromEntityMapsEveryPopulatedField() {
        Report report = new Report();
        report.setId(42L);
        report.setReportName("Monthly Usage");
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(ReportType.CSV);
        report.setStatus(ReportStatus.COMPLETED);
        report.setRequestedBy("user-1");
        report.setDateFrom(FROM);
        report.setDateTo(TO);
        report.setCreatedAt(FROM);
        report.setCompletedAt(TO);
        report.setFileSizeBytes(2048L);
        report.setRowCount(17);
        report.setFilePath("/tmp/reports/monthly_usage.csv");
        report.setErrorMessage(null);

        ReportResponse response = ReportResponse.fromEntity(report);

        assertEquals(Long.valueOf(42L), response.getId());
        assertEquals("Monthly Usage", response.getReportName());
        assertEquals("USAGE_ANALYTICS", response.getCategory());
        assertEquals("CSV", response.getReportType());
        assertEquals("COMPLETED", response.getStatus());
        assertEquals("user-1", response.getRequestedBy());
        assertEquals(FROM, response.getDateFrom());
        assertEquals(TO, response.getDateTo());
        assertEquals(FROM, response.getCreatedAt());
        assertEquals(TO, response.getCompletedAt());
        assertEquals(Long.valueOf(2048L), response.getFileSizeBytes());
        assertEquals(Integer.valueOf(17), response.getRowCount());
        assertEquals("/api/v1/reports/42/download", response.getDownloadUrl());
        assertNull(response.getErrorMessage());
    }

    @Test
    public void fromEntityLeavesEnumStringsNullWhenEnumsAreUnset() {
        Report report = new Report();
        report.setId(7L);
        report.setReportName("Draft");

        ReportResponse response = ReportResponse.fromEntity(report);

        assertNull(response.getCategory());
        assertNull(response.getReportType());
        assertNull(response.getStatus());
        assertNull(response.getDownloadUrl());
        assertEquals("Draft", response.getReportName());
    }

    @Test
    public void fromEntityOmitsDownloadUrlUntilAFileExists() {
        Report report = new Report();
        report.setId(9L);
        report.setStatus(ReportStatus.GENERATING);
        report.setFilePath(null);

        assertNull(ReportResponse.fromEntity(report).getDownloadUrl());

        report.setFilePath("/tmp/reports/r9.pdf");
        assertEquals("/api/v1/reports/9/download", ReportResponse.fromEntity(report).getDownloadUrl());
    }

    @Test
    public void fromEntityPropagatesFailureMessage() {
        Report report = new Report();
        report.setId(3L);
        report.setStatus(ReportStatus.FAILED);
        report.setErrorMessage("disk full");

        ReportResponse response = ReportResponse.fromEntity(report);

        assertEquals("FAILED", response.getStatus());
        assertEquals("disk full", response.getErrorMessage());
    }

    @Test
    public void settersAndGettersRoundTrip() {
        ReportResponse response = new ReportResponse();
        response.setId(1L);
        response.setReportName("Ad hoc");
        response.setCategory("AUDIT_LOG");
        response.setReportType("PDF");
        response.setStatus("PENDING");
        response.setRequestedBy("user-2");
        response.setDateFrom(FROM);
        response.setDateTo(TO);
        response.setCreatedAt(FROM);
        response.setCompletedAt(TO);
        response.setFileSizeBytes(10L);
        response.setRowCount(1);
        response.setDownloadUrl("/api/v1/reports/1/download");
        response.setErrorMessage("none");

        assertEquals(Long.valueOf(1L), response.getId());
        assertEquals("Ad hoc", response.getReportName());
        assertEquals("AUDIT_LOG", response.getCategory());
        assertEquals("PDF", response.getReportType());
        assertEquals("PENDING", response.getStatus());
        assertEquals("user-2", response.getRequestedBy());
        assertEquals(FROM, response.getDateFrom());
        assertEquals(TO, response.getDateTo());
        assertEquals(FROM, response.getCreatedAt());
        assertEquals(TO, response.getCompletedAt());
        assertEquals(Long.valueOf(10L), response.getFileSizeBytes());
        assertEquals(Integer.valueOf(1), response.getRowCount());
        assertEquals("/api/v1/reports/1/download", response.getDownloadUrl());
        assertEquals("none", response.getErrorMessage());
    }
}
