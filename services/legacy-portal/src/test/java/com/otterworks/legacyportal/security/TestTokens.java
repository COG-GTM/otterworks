package com.otterworks.legacyportal.security;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Arrays;
import java.util.Date;
import javax.crypto.SecretKey;

/** Mints tokens shaped like auth-service's, signed with the test JWT secret. */
public final class TestTokens {

    public static final String SECRET = "test-jwt-secret-legacy-portal-must-be-at-least-32-bytes";

    private TestTokens() {}

    public static String bearer(String userId, String... roles) {
        return "Bearer " + access(key(SECRET), userId, 3600, roles);
    }

    public static String access(SecretKey key, String userId, long ttlSeconds, String... roles) {
        Instant now = Instant.now();
        return Jwts.builder()
                .setSubject(userId)
                .claim("roles", Arrays.asList(roles))
                .claim("type", "access")
                .setIssuedAt(Date.from(now.minusSeconds(5)))
                .setExpiration(Date.from(now.plusSeconds(ttlSeconds)))
                .signWith(key)
                .compact();
    }

    public static String refresh(String userId) {
        Instant now = Instant.now();
        return Jwts.builder()
                .setSubject(userId)
                .setId("jti-1")
                .claim("type", "refresh")
                .setIssuedAt(Date.from(now))
                .setExpiration(Date.from(now.plusSeconds(3600)))
                .signWith(key(SECRET))
                .compact();
    }

    public static SecretKey key(String secret) {
        return Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
    }
}
