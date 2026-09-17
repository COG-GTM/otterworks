package com.otterworks.report.model;

import org.junit.Test;

import java.util.Date;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * Unit tests for the {@link Report} entity's accessors and {@code toString()}.
 *
 * The generation pipeline writes the completion fields (file path, size, row count, error) after
 * the entity is first persisted; those setters are only reachable here.
 */
public class ReportTest {

    /** 2024-01-01T00:00:00Z */
    private static final Date CREATED = new Date(1_704_067_200_000L);

    /** 2024-01-08T00:00:00Z */
    private static final Date COMPLETED = new Date(1_704_672_000_000L);

    @Test
    public void newReportHasNoFieldsSet() {
        Report report = new Report();

        assertNull(report.getId());
        assertNull(report.getReportName());
        assertNull(report.getCategory());
        assertNull(report.getReportType());
        assertNull(report.getStatus());
        assertNull(report.getRequestedBy());
        assertNull(report.getDateFrom());
        assertNull(report.getDateTo());
        assertNull(report.getCreatedAt());
        assertNull(report.getCompletedAt());
        assertNull(report.getFilePath());
        assertNull(report.getFileSizeBytes());
        assertNull(report.getRowCount());
        assertNull(report.getErrorMessage());
        assertNull(report.getParameters());
    }

    @Test
    public void everyFieldRoundTripsThroughItsAccessors() {
        Report report = fullyPopulated();

        assertEquals(Long.valueOf(1L), report.getId());
        assertEquals("Weekly Usage", report.getReportName());
        assertEquals(ReportCategory.AUDIT_LOG, report.getCategory());
        assertEquals(ReportType.EXCEL, report.getReportType());
        assertEquals(ReportStatus.COMPLETED, report.getStatus());
        assertEquals("user-1", report.getRequestedBy());
        assertEquals(CREATED, report.getDateFrom());
        assertEquals(COMPLETED, report.getDateTo());
        assertEquals(CREATED, report.getCreatedAt());
        assertEquals(COMPLETED, report.getCompletedAt());
        assertEquals("/tmp/reports/weekly.xlsx", report.getFilePath());
        assertEquals(Long.valueOf(2048L), report.getFileSizeBytes());
        assertEquals(Integer.valueOf(120), report.getRowCount());
        assertEquals("boom", report.getErrorMessage());
        assertEquals("{\"metric\":\"downloads\"}", report.getParameters());
    }

    @Test
    public void toStringSummarisesTheIdentifyingFields() {
        String text = fullyPopulated().toString();

        assertTrue(text, text.startsWith("Report{id=1,"));
        assertTrue(text, text.contains("reportName='Weekly Usage'"));
        assertTrue(text, text.contains("category=AUDIT_LOG"));
        assertTrue(text, text.contains("reportType=EXCEL"));
        assertTrue(text, text.contains("status=COMPLETED"));
        assertTrue(text, text.contains("requestedBy='user-1'"));
    }

    private static Report fullyPopulated() {
        Report report = new Report();
        report.setId(1L);
        report.setReportName("Weekly Usage");
        report.setCategory(ReportCategory.AUDIT_LOG);
        report.setReportType(ReportType.EXCEL);
        report.setStatus(ReportStatus.COMPLETED);
        report.setRequestedBy("user-1");
        report.setDateFrom(CREATED);
        report.setDateTo(COMPLETED);
        report.setCreatedAt(CREATED);
        report.setCompletedAt(COMPLETED);
        report.setFilePath("/tmp/reports/weekly.xlsx");
        report.setFileSizeBytes(2048L);
        report.setRowCount(120);
        report.setErrorMessage("boom");
        report.setParameters("{\"metric\":\"downloads\"}");
        return report;
    }
}
