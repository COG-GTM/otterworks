package com.otterworks.report.model;

import org.junit.Test;

import java.util.Date;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * Unit tests for the {@link Report} JPA entity's accessors and {@code toString()}.
 */
public class ReportTest {

    private static final Date CREATED = new Date(1_704_067_200_000L); // 2024-01-01T00:00:00Z
    private static final Date COMPLETED = new Date(1_704_067_260_000L); // +60s

    @Test
    public void newReportHasNoStateUntilPopulated() {
        Report report = new Report();

        assertNull(report.getId());
        assertNull(report.getReportName());
        assertNull(report.getCategory());
        assertNull(report.getReportType());
        assertNull(report.getStatus());
        assertNull(report.getFilePath());
        assertNull(report.getFileSizeBytes());
        assertNull(report.getRowCount());
        assertNull(report.getErrorMessage());
        assertNull(report.getParameters());
        assertNull(report.getCompletedAt());
    }

    @Test
    public void accessorsRoundTripEveryColumn() {
        Report report = new Report();
        report.setId(11L);
        report.setReportName("Quarterly Audit");
        report.setCategory(ReportCategory.AUDIT_LOG);
        report.setReportType(ReportType.EXCEL);
        report.setStatus(ReportStatus.COMPLETED);
        report.setRequestedBy("auditor-1");
        report.setDateFrom(CREATED);
        report.setDateTo(COMPLETED);
        report.setCreatedAt(CREATED);
        report.setCompletedAt(COMPLETED);
        report.setFilePath("/tmp/reports/quarterly_audit.xlsx");
        report.setFileSizeBytes(4096L);
        report.setRowCount(120);
        report.setErrorMessage("none");
        report.setParameters("{\"metric\":\"logins\"}");

        assertEquals(Long.valueOf(11L), report.getId());
        assertEquals("Quarterly Audit", report.getReportName());
        assertEquals(ReportCategory.AUDIT_LOG, report.getCategory());
        assertEquals(ReportType.EXCEL, report.getReportType());
        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        assertEquals("auditor-1", report.getRequestedBy());
        assertEquals(CREATED, report.getDateFrom());
        assertEquals(COMPLETED, report.getDateTo());
        assertEquals(CREATED, report.getCreatedAt());
        assertEquals(COMPLETED, report.getCompletedAt());
        assertEquals("/tmp/reports/quarterly_audit.xlsx", report.getFilePath());
        assertEquals(Long.valueOf(4096L), report.getFileSizeBytes());
        assertEquals(Integer.valueOf(120), report.getRowCount());
        assertEquals("none", report.getErrorMessage());
        assertEquals("{\"metric\":\"logins\"}", report.getParameters());
    }

    @Test
    public void toStringSummarisesTheIdentifyingFields() {
        Report report = new Report();
        report.setId(5L);
        report.setReportName("Storage Summary");
        report.setCategory(ReportCategory.STORAGE_SUMMARY);
        report.setReportType(ReportType.CSV);
        report.setStatus(ReportStatus.PENDING);
        report.setRequestedBy("user-9");
        report.setCreatedAt(CREATED);

        String text = report.toString();

        assertTrue(text, text.startsWith("Report{"));
        assertTrue(text, text.contains("id=5"));
        assertTrue(text, text.contains("reportName='Storage Summary'"));
        assertTrue(text, text.contains("category=STORAGE_SUMMARY"));
        assertTrue(text, text.contains("reportType=CSV"));
        assertTrue(text, text.contains("status=PENDING"));
        assertTrue(text, text.contains("requestedBy='user-9'"));
    }
}
