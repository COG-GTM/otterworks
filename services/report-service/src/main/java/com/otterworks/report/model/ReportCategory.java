package com.otterworks.report.model;

/**
 * Categories of reports available in the system.
 */
public enum ReportCategory {
    /** User activity and usage analytics */
    USAGE_ANALYTICS,
    /** Security audit trail */
    AUDIT_LOG,
    /** File storage statistics */
    STORAGE_SUMMARY,
    /** User account overview */
    USER_ACTIVITY,
    /** Document collaboration metrics */
    COLLABORATION_METRICS,
    /** System health and performance */
    SYSTEM_HEALTH,
    /** Compliance and regulatory */
    COMPLIANCE;

    /**
     * Whether the report's data covers every user on the platform (audit trail or user
     * activity) rather than aggregate metrics, so only administrators may request it.
     */
    public boolean isAdminOnly() {
        switch (this) {
            case AUDIT_LOG:
            case COMPLIANCE:
            case USER_ACTIVITY:
            case STORAGE_SUMMARY:
                return true;
            default:
                return false;
        }
    }
}
