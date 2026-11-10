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

    /** Categories built from platform-wide audit or user activity data, restricted to administrators. */
    public boolean requiresAdmin() {
        return this == AUDIT_LOG || this == COMPLIANCE || this == USER_ACTIVITY || this == STORAGE_SUMMARY;
    }
}
