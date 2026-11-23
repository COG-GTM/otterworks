package com.otterworks.legacyportal.security;

import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;

/** auth-service roles allowed to manage portal content (create, publish, see drafts). */
public final class PortalRoles {

    public static final String ADMIN = "ADMIN";
    public static final String OWNER = "OWNER";

    static final String[] CONTENT_ADMIN_ROLES = {ADMIN, OWNER};

    private PortalRoles() {}

    public static boolean isContentAdmin(Authentication authentication) {
        if (authentication == null || !authentication.isAuthenticated()) {
            return false;
        }
        for (GrantedAuthority authority : authentication.getAuthorities()) {
            for (String role : CONTENT_ADMIN_ROLES) {
                if (("ROLE_" + role).equals(authority.getAuthority())) {
                    return true;
                }
            }
        }
        return false;
    }
}
