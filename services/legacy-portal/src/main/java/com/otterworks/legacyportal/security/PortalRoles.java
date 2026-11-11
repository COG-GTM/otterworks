package com.otterworks.legacyportal.security;

import org.springframework.security.core.Authentication;

/** Role names carried in auth-service's {@code roles} claim. */
public final class PortalRoles {

    public static final String ADMIN = "ADMIN";
    private static final String ADMIN_AUTHORITY = "ROLE_" + ADMIN;

    private PortalRoles() {}

    public static boolean isAdmin(Authentication authentication) {
        return authentication != null
                && authentication.getAuthorities().stream()
                        .anyMatch(a -> ADMIN_AUTHORITY.equals(a.getAuthority()));
    }
}
