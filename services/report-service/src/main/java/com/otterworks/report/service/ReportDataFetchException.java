package com.otterworks.report.service;

/**
 * Raised when report source data cannot be fetched from an upstream service.
 * The message is user-facing (stored as the report's errorMessage); the cause
 * carries the upstream details for logs.
 */
public class ReportDataFetchException extends RuntimeException {

    public ReportDataFetchException(String message, Throwable cause) {
        super(message, cause);
    }
}
