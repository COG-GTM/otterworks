package com.otterworks.report.security;

import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/**
 * Authenticated identity of the caller of the report API, derived from a verified JWT.
 */
public final class ReportCaller {

    private static final Set<String> ADMIN_ROLES = Collections.unmodifiableSet(
            new HashSet<>(Arrays.asList("ADMIN", "OWNER")));

    private final String userId;
    private final Set<String> roles;

    public ReportCaller(String userId, Set<String> roles) {
        if (userId == null || userId.trim().isEmpty()) {
            throw new IllegalArgumentException("userId is required");
        }
        this.userId = userId;
        Set<String> normalized = new HashSet<>();
        if (roles != null) {
            for (String role : roles) {
                if (role != null) {
                    normalized.add(role.trim().toUpperCase(Locale.ROOT));
                }
            }
        }
        this.roles = Collections.unmodifiableSet(normalized);
    }

    public static ReportCaller current() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()
                || authentication instanceof AnonymousAuthenticationToken
                || !(authentication.getPrincipal() instanceof String)) {
            throw new IllegalStateException("No authenticated report caller");
        }
        Set<String> roles = new HashSet<>();
        for (GrantedAuthority authority : authentication.getAuthorities()) {
            String name = authority.getAuthority();
            if (name != null && name.startsWith("ROLE_")) {
                roles.add(name.substring("ROLE_".length()));
            }
        }
        return new ReportCaller((String) authentication.getPrincipal(), roles);
    }

    public String getUserId() {
        return userId;
    }

    public Set<String> getRoles() {
        return roles;
    }

    public boolean isAdmin() {
        for (String role : roles) {
            if (ADMIN_ROLES.contains(role)) {
                return true;
            }
        }
        return false;
    }

    public boolean owns(String requestedBy) {
        return userId.equals(requestedBy);
    }
}
