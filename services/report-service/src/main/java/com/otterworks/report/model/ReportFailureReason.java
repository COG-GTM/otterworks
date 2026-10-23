package com.otterworks.report.model;

/**
 * Client-facing cause of a failed report.
 *
 * Only the enum name is persisted on the report; exception detail stays in the server log.
 */
public enum ReportFailureReason {
    DATA_SOURCE_UNAVAILABLE("Report data could not be retrieved. Try again later."),
    INVALID_PARAMETERS("Report parameters are invalid."),
    GENERATION_FAILED("Report generation failed.");

    private final String message;

    ReportFailureReason(String message) {
        this.message = message;
    }

    public String getMessage() {
        return message;
    }

    /**
     * Maps a stored error value to a reason. Anything that is not a known reason name
     * (e.g. raw exception text persisted by older builds) becomes GENERATION_FAILED.
     */
    public static ReportFailureReason fromStoredValue(String stored) {
        if (stored == null) {
            return null;
        }
        for (ReportFailureReason reason : values()) {
            if (reason.name().equals(stored)) {
                return reason;
            }
        }
        return GENERATION_FAILED;
    }
}
