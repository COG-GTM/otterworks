package com.otterworks.report.model;

import org.junit.Test;

import java.util.Date;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * Tests the mapping and rendering logic on the report model classes.
 *
 * Written in JUnit 4 style to match the current stack.
 */
public class ReportModelTest {

    private static final Date FROM = new Date(1704067200000L);
    private static final Date TO = new Date(1704153600000L);

    @Test
    public void fromEntityMapsEveryPopulatedField() {
        Report report = new Report();
        report.setId(1L);
        report.setReportName("Usage Report");
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(ReportType.EXCEL);
        report.setStatus(ReportStatus.COMPLETED);
        report.setRequestedBy("user-1");
        report.setDateFrom(FROM);
        report.setDateTo(TO);
        report.setRowCount(12);
        report.setFileSizeBytes(2048L);

        ReportResponse response = ReportResponse.fromEntity(report);

        assertEquals(Long.valueOf(1L), response.getId());
        assertEquals("Usage Report", response.getReportName());
        assertEquals("USAGE_ANALYTICS", response.getCategory());
        assertEquals("EXCEL", response.getReportType());
        assertEquals("COMPLETED", response.getStatus());
        assertEquals("user-1", response.getRequestedBy());
        assertEquals(FROM, response.getDateFrom());
        assertEquals(TO, response.getDateTo());
        assertEquals(Integer.valueOf(12), response.getRowCount());
        assertEquals(Long.valueOf(2048L), response.getFileSizeBytes());
    }

    @Test
    public void fromEntityLeavesEnumFieldsNullWhenUnset() {
        Report report = new Report();
        report.setId(2L);
        report.setReportName("Draft");

        ReportResponse response = ReportResponse.fromEntity(report);

        assertNull(response.getCategory());
        assertNull(response.getReportType());
        assertNull(response.getStatus());
        assertEquals("Draft", response.getReportName());
    }

    @Test
    public void reportToStringSummarisesTheKeyFields() {
        Report report = new Report();
        report.setId(3L);
        report.setReportName("Audit Export");
        report.setCategory(ReportCategory.AUDIT_LOG);
        report.setReportType(ReportType.CSV);
        report.setStatus(ReportStatus.FAILED);

        String rendered = report.toString();

        assertTrue(rendered, rendered.startsWith("Report{"));
        assertTrue(rendered, rendered.contains("id=3"));
        assertTrue(rendered, rendered.contains("reportName='Audit Export'"));
        assertTrue(rendered, rendered.contains("category=AUDIT_LOG"));
        assertTrue(rendered, rendered.contains("reportType=CSV"));
        assertTrue(rendered, rendered.contains("FAILED"));
    }
}
