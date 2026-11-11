package com.otterworks.report.model;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

public class ReportResponseTest {

    @Test
    public void fromEntityReplacesStoredErrorDetailWithGenericMessage() {
        Report report = new Report();
        report.setStatus(ReportStatus.FAILED);
        report.setErrorMessage("I/O error on GET request for \"http://analytics-service:8088/api/v1/analytics/dashboard\"");

        ReportResponse response = ReportResponse.fromEntity(report);

        assertEquals(Report.GENERATION_FAILED_MESSAGE, response.getErrorMessage());
    }

    @Test
    public void fromEntityLeavesErrorMessageNullWhenNoFailure() {
        Report report = new Report();
        report.setStatus(ReportStatus.COMPLETED);

        assertNull(ReportResponse.fromEntity(report).getErrorMessage());
    }
}
