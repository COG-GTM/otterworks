package com.otterworks.report.service;

/**
 * Thrown when the caller is authenticated but not allowed to perform a report action.
 */
public class ReportAccessDeniedException extends RuntimeException {

    public ReportAccessDeniedException(String message) {
        super(message);
    }
}
