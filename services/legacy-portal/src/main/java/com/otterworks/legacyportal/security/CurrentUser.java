package com.otterworks.legacyportal.security;

import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;

/** The authenticated caller, as established by {@link SecurityConfig}. */
public final class CurrentUser {

    static final String[] ADMIN_ROLES = {"ADMIN", "OWNER"};

    private CurrentUser() {
    }

    /** The caller's user id: the access token's subject. */
    public static String id(Authentication authentication) {
        return authentication.getName();
    }

    public static boolean isAdmin(Authentication authentication) {
        for (GrantedAuthority authority : authentication.getAuthorities()) {
            for (String role : ADMIN_ROLES) {
                if (("ROLE_" + role).equals(authority.getAuthority())) {
                    return true;
                }
            }
        }
        return false;
    }
}
