package com.otterworks.report.security;

import java.util.Collections;
import java.util.Set;

/**
 * The authenticated identity behind a report request.
 */
public final class ReportCaller {

    public static final String ADMIN_ROLE = "ADMIN";

    private final String userId;
    private final Set<String> roles;

    public ReportCaller(String userId, Set<String> roles) {
        this.userId = userId;
        this.roles = Collections.unmodifiableSet(roles);
    }

    public String getUserId() {
        return userId;
    }

    public Set<String> getRoles() {
        return roles;
    }

    public boolean isAdmin() {
        return roles.contains(ADMIN_ROLE);
    }

    @Override
    public String toString() {
        return userId;
    }
}
