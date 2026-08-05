package com.otterworks.report.model;

import org.junit.Test;

import java.util.Date;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * Unit tests for the {@link Report} JPA entity.
 *
 * The entity is a plain mutable POJO: the contract worth pinning down is that every
 * persisted attribute round-trips through its accessors and that {@code toString()} keeps
 * exposing the identifying fields used in the service logs.
 */
public class ReportTest {

    private static final Date CREATED_AT = new Date(1_704_067_200_000L); // 2024-01-01T00:00:00Z
    private static final Date COMPLETED_AT = new Date(1_704_067_260_000L);

    @Test
    public void everyAttributeRoundTripsThroughItsAccessors() {
        Report report = new Report();

        report.setId(9L);
        report.setReportName("Q1 audit");
        report.setCategory(ReportCategory.AUDIT_LOG);
        report.setReportType(ReportType.EXCEL);
        report.setStatus(ReportStatus.COMPLETED);
        report.setRequestedBy("user-9");
        report.setDateFrom(CREATED_AT);
        report.setDateTo(COMPLETED_AT);
        report.setCreatedAt(CREATED_AT);
        report.setCompletedAt(COMPLETED_AT);
        report.setFilePath("/tmp/reports/q1_audit.xlsx");
        report.setFileSizeBytes(2048L);
        report.setRowCount(120);
        report.setErrorMessage(null);
        report.setParameters("{\"region\":\"emea\"}");

        assertEquals(Long.valueOf(9L), report.getId());
        assertEquals("Q1 audit", report.getReportName());
        assertEquals(ReportCategory.AUDIT_LOG, report.getCategory());
        assertEquals(ReportType.EXCEL, report.getReportType());
        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        assertEquals("user-9", report.getRequestedBy());
        assertEquals(CREATED_AT, report.getDateFrom());
        assertEquals(COMPLETED_AT, report.getDateTo());
        assertEquals(CREATED_AT, report.getCreatedAt());
        assertEquals(COMPLETED_AT, report.getCompletedAt());
        assertEquals("/tmp/reports/q1_audit.xlsx", report.getFilePath());
        assertEquals(Long.valueOf(2048L), report.getFileSizeBytes());
        assertEquals(Integer.valueOf(120), report.getRowCount());
        assertNull(report.getErrorMessage());
        assertEquals("{\"region\":\"emea\"}", report.getParameters());
    }

    @Test
    public void aFreshReportHasNoStateSet() {
        Report report = new Report();

        assertNull(report.getId());
        assertNull(report.getStatus());
        assertNull(report.getCreatedAt());
        assertNull(report.getCompletedAt());
        assertNull(report.getFilePath());
        assertNull(report.getFileSizeBytes());
        assertNull(report.getRowCount());
        assertNull(report.getParameters());
    }

    @Test
    public void failedReportsCarryTheirErrorMessage() {
        Report report = new Report();
        report.setStatus(ReportStatus.FAILED);
        report.setErrorMessage("disk full");

        assertEquals(ReportStatus.FAILED, report.getStatus());
        assertEquals("disk full", report.getErrorMessage());
    }

    @Test
    public void toStringExposesTheIdentifyingFields() {
        Report report = new Report();
        report.setId(9L);
        report.setReportName("Q1 audit");
        report.setCategory(ReportCategory.AUDIT_LOG);
        report.setReportType(ReportType.EXCEL);
        report.setStatus(ReportStatus.COMPLETED);
        report.setRequestedBy("user-9");
        report.setCreatedAt(CREATED_AT);

        String text = report.toString();

        assertTrue(text, text.startsWith("Report{id=9"));
        assertTrue(text, text.contains("reportName='Q1 audit'"));
        assertTrue(text, text.contains("category=AUDIT_LOG"));
        assertTrue(text, text.contains("reportType=EXCEL"));
        assertTrue(text, text.contains("status=COMPLETED"));
        assertTrue(text, text.contains("requestedBy='user-9'"));
        assertTrue(text, text.contains("createdAt=" + CREATED_AT));
        assertTrue(text, text.endsWith("}"));
    }

    @Test
    public void enumsCoverTheDocumentedDomain() {
        assertEquals(3, ReportType.values().length);
        assertEquals(ReportType.PDF, ReportType.valueOf("PDF"));
        assertEquals(4, ReportStatus.values().length);
        assertEquals(ReportStatus.GENERATING, ReportStatus.valueOf("GENERATING"));
        assertEquals(7, ReportCategory.values().length);
        assertEquals(ReportCategory.COMPLIANCE, ReportCategory.valueOf("COMPLIANCE"));
    }
}
