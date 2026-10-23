package com.otterworks.report.model;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

public class ReportResponseTest {

    @Test
    public void legacyRawErrorTextIsNotReturned() {
        Report report = new Report();
        report.setId(3L);
        report.setStatus(ReportStatus.FAILED);
        report.setErrorMessage("I/O error on GET request for \"http://audit-service:8090/api/v1/audit/events\"");

        ReportResponse response = ReportResponse.fromEntity(report);

        assertEquals("GENERATION_FAILED", response.getFailureReason());
        assertEquals(ReportFailureReason.GENERATION_FAILED.getMessage(), response.getErrorMessage());
    }

    @Test
    public void knownReasonCodeMapsToItsMessage() {
        Report report = new Report();
        report.setStatus(ReportStatus.FAILED);
        report.setErrorMessage("INVALID_PARAMETERS");

        ReportResponse response = ReportResponse.fromEntity(report);

        assertEquals("INVALID_PARAMETERS", response.getFailureReason());
        assertEquals(ReportFailureReason.INVALID_PARAMETERS.getMessage(), response.getErrorMessage());
    }

    @Test
    public void legacyFailedReportWithoutStoredMessageGetsGenericReason() {
        Report report = new Report();
        report.setStatus(ReportStatus.FAILED);

        ReportResponse response = ReportResponse.fromEntity(report);

        assertEquals("GENERATION_FAILED", response.getFailureReason());
        assertEquals(ReportFailureReason.GENERATION_FAILED.getMessage(), response.getErrorMessage());
    }

    @Test
    public void successfulReportHasNoError() {
        Report report = new Report();
        report.setStatus(ReportStatus.COMPLETED);

        ReportResponse response = ReportResponse.fromEntity(report);

        assertNull(response.getFailureReason());
        assertNull(response.getErrorMessage());
    }
}
