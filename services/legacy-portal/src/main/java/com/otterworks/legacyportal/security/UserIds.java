package com.otterworks.legacyportal.security;

import java.util.regex.Pattern;

/** Format rules for portal user ids (path variables and token subjects). */
public final class UserIds {

    /** Matches auth-service UUID subjects; bounded by the 100-char {@code user_id} columns. */
    private static final Pattern USER_ID = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._@-]{0,99}");

    private UserIds() {}

    public static boolean isValid(String userId) {
        return userId != null && USER_ID.matcher(userId).matches();
    }

    public static String requireValid(String userId) {
        if (!isValid(userId)) {
            throw new IllegalArgumentException("Invalid userId");
        }
        return userId;
    }
}
