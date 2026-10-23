package com.otterworks.legacyportal.security;

import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Set;

/** The caller identified by a verified auth-service access token. */
public final class PortalPrincipal {

    static final String ADMIN_ROLE = "ADMIN";

    private final String userId;
    private final Set<String> roles;

    public PortalPrincipal(String userId, Set<String> roles) {
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

    /** Whether this caller may act on {@code userId}'s data: their own, or any user's as admin. */
    public boolean canAccessUser(String userId) {
        return this.userId.equals(userId) || isAdmin();
    }

    @Override
    public String toString() {
        return userId;
    }
}
