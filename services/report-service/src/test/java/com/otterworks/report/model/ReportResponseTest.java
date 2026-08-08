package com.otterworks.report.model;

import org.junit.Test;

import java.util.Date;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

/**
 * Unit tests for {@link ReportResponse#fromEntity(Report)} and its accessors.
 */
public class ReportResponseTest {

    /** 2024-01-01T00:00:00Z */
    private static final Date CREATED = new Date(1_704_067_200_000L);

    /** 2024-01-08T00:00:00Z */
    private static final Date COMPLETED = new Date(1_704_672_000_000L);

    @Test
    public void fromEntityMapsEveryPopulatedField() {
        Report report = new Report();
        report.setId(9L);
        report.setReportName("Weekly Usage");
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(ReportType.CSV);
        report.setStatus(ReportStatus.COMPLETED);
        report.setRequestedBy("user-1");
        report.setDateFrom(CREATED);
        report.setDateTo(COMPLETED);
        report.setCreatedAt(CREATED);
        report.setCompletedAt(COMPLETED);
        report.setFileSizeBytes(1024L);
        report.setRowCount(50);
        report.setFilePath("/tmp/reports/weekly.csv");
        report.setErrorMessage("none");

        ReportResponse response = ReportResponse.fromEntity(report);

        assertEquals(Long.valueOf(9L), response.getId());
        assertEquals("Weekly Usage", response.getReportName());
        assertEquals("USAGE_ANALYTICS", response.getCategory());
        assertEquals("CSV", response.getReportType());
        assertEquals("COMPLETED", response.getStatus());
        assertEquals("user-1", response.getRequestedBy());
        assertEquals(CREATED, response.getDateFrom());
        assertEquals(COMPLETED, response.getDateTo());
        assertEquals(CREATED, response.getCreatedAt());
        assertEquals(COMPLETED, response.getCompletedAt());
        assertEquals(Long.valueOf(1024L), response.getFileSizeBytes());
        assertEquals(Integer.valueOf(50), response.getRowCount());
        assertEquals("/api/v1/reports/9/download", response.getDownloadUrl());
        assertEquals("none", response.getErrorMessage());
    }

    @Test
    public void fromEntityLeavesEnumStringsNullWhenTheEntityHasNone() {
        ReportResponse response = ReportResponse.fromEntity(new Report());

        assertNull(response.getCategory());
        assertNull(response.getReportType());
        assertNull(response.getStatus());
    }

    @Test
    public void fromEntityOmitsTheDownloadUrlUntilAFileExists() {
        Report report = new Report();
        report.setId(9L);
        report.setStatus(ReportStatus.GENERATING);

        assertNull(ReportResponse.fromEntity(report).getDownloadUrl());
    }

    @Test
    public void everyFieldRoundTripsThroughItsAccessors() {
        ReportResponse response = new ReportResponse();
        response.setId(3L);
        response.setReportName("Audit Trail");
        response.setCategory("AUDIT_LOG");
        response.setReportType("PDF");
        response.setStatus("FAILED");
        response.setRequestedBy("user-2");
        response.setDateFrom(CREATED);
        response.setDateTo(COMPLETED);
        response.setCreatedAt(CREATED);
        response.setCompletedAt(COMPLETED);
        response.setFileSizeBytes(64L);
        response.setRowCount(2);
        response.setDownloadUrl("/api/v1/reports/3/download");
        response.setErrorMessage("boom");

        assertEquals(Long.valueOf(3L), response.getId());
        assertEquals("Audit Trail", response.getReportName());
        assertEquals("AUDIT_LOG", response.getCategory());
        assertEquals("PDF", response.getReportType());
        assertEquals("FAILED", response.getStatus());
        assertEquals("user-2", response.getRequestedBy());
        assertEquals(CREATED, response.getDateFrom());
        assertEquals(COMPLETED, response.getDateTo());
        assertEquals(CREATED, response.getCreatedAt());
        assertEquals(COMPLETED, response.getCompletedAt());
        assertEquals(Long.valueOf(64L), response.getFileSizeBytes());
        assertEquals(Integer.valueOf(2), response.getRowCount());
        assertEquals("/api/v1/reports/3/download", response.getDownloadUrl());
        assertEquals("boom", response.getErrorMessage());
    }
}
