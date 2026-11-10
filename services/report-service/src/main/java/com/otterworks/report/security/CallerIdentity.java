package com.otterworks.report.security;

import org.springframework.security.oauth2.jwt.Jwt;

import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.List;

/**
 * The authenticated caller of a report endpoint, derived only from a verified access token.
 */
public final class CallerIdentity {

    private static final List<String> ADMIN_ROLES = Arrays.asList("ADMIN", "OWNER", "SUPER_ADMIN");

    private final String userId;
    private final boolean admin;

    private CallerIdentity(String userId, boolean admin) {
        this.userId = userId;
        this.admin = admin;
    }

    public static CallerIdentity from(Jwt jwt) {
        return new CallerIdentity(userIdOf(jwt), hasAdminRole(jwt));
    }

    static String userIdOf(Jwt jwt) {
        String subject = jwt.getSubject();
        if (subject != null && !subject.trim().isEmpty()) {
            return subject;
        }
        String userId = jwt.getClaimAsString("user_id");
        return userId != null && !userId.trim().isEmpty() ? userId : null;
    }

    private static boolean hasAdminRole(Jwt jwt) {
        for (String claim : Arrays.asList("roles", "role")) {
            for (Object role : claimValues(jwt.getClaims().get(claim))) {
                if (role != null && ADMIN_ROLES.contains(role.toString().trim().toUpperCase())) {
                    return true;
                }
            }
        }
        return false;
    }

    private static Collection<?> claimValues(Object value) {
        if (value instanceof Collection) {
            return (Collection<?>) value;
        }
        return value == null ? Collections.emptyList() : Collections.singletonList(value);
    }

    public String getUserId() {
        return userId;
    }

    public boolean isAdmin() {
        return admin;
    }
}
