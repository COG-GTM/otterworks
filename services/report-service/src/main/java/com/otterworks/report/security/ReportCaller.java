package com.otterworks.report.security;

import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Collections;
import java.util.List;
import java.util.Optional;

/**
 * The authenticated caller of a report endpoint, from a verified JWT or the api-gateway identity headers.
 */
public final class ReportCaller {

    public static final String ADMIN_ROLE = "ADMIN";

    private final String userId;
    private final List<String> roles;

    public ReportCaller(String userId, List<String> roles) {
        this.userId = userId;
        this.roles = roles == null ? Collections.<String>emptyList() : Collections.unmodifiableList(roles);
    }

    public String getUserId() {
        return userId;
    }

    public List<String> getRoles() {
        return roles;
    }

    public boolean isAdmin() {
        return roles.contains(ADMIN_ROLE);
    }

    public boolean owns(String requestedBy) {
        return userId.equals(requestedBy);
    }

    public static Optional<ReportCaller> current() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.getPrincipal() instanceof ReportCaller) {
            return Optional.of((ReportCaller) authentication.getPrincipal());
        }
        return Optional.empty();
    }

    @Override
    public String toString() {
        return userId;
    }
}
