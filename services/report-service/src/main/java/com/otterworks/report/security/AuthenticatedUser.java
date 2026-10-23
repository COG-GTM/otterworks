package com.otterworks.report.security;

import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Set;

/**
 * Caller identity taken from a verified access token.
 */
public final class AuthenticatedUser {

    public static final String ADMIN_ROLE = "ADMIN";

    private final String userId;
    private final Set<String> roles;

    public AuthenticatedUser(String userId, Set<String> roles) {
        this.userId = userId;
        this.roles = Collections.unmodifiableSet(new LinkedHashSet<>(roles));
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

    public boolean owns(String requestedBy) {
        return userId.equals(requestedBy);
    }

    @Override
    public String toString() {
        return userId;
    }
}
