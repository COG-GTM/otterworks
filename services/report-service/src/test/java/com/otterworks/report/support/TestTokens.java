package com.otterworks.report.support;

import com.otterworks.report.model.ReportRequest;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.http.HttpHeaders;
import org.springframework.test.web.servlet.request.RequestPostProcessor;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Date;

/**
 * Mints auth-service style access tokens signed with the test profile's JWT secret.
 */
public final class TestTokens {

    /** Must match otterworks.jwt.secret in application-test.properties. */
    public static final String SECRET = "report-service-test-jwt-secret-0123456789abcdef";

    private TestTokens() {
    }

    public static String token(String userId, String... roles) {
        return signedToken(SECRET, userId, "access", roles);
    }

    public static String signedToken(String secret, String userId, String type, String... roles) {
        SecretKey key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        return Jwts.builder()
                .setSubject(userId)
                .claim("roles", Arrays.asList(roles))
                .claim("type", type)
                .setIssuedAt(new Date())
                .setExpiration(new Date(System.currentTimeMillis() + 3600_000L))
                .signWith(key)
                .compact();
    }

    public static RequestPostProcessor bearer(String token) {
        return request -> {
            request.addHeader(HttpHeaders.AUTHORIZATION, "Bearer " + token);
            return request;
        };
    }

    public static RequestPostProcessor user(String userId) {
        return bearer(token(userId, "USER"));
    }

    public static RequestPostProcessor admin(String userId) {
        return bearer(token(userId, "USER", "ADMIN"));
    }

    /**
     * Authenticates as the request's requestedBy, with the admin role only when the
     * category requires it.
     */
    public static RequestPostProcessor requesterOf(ReportRequest request) {
        String userId = request.getRequestedBy() != null ? request.getRequestedBy() : "test-user";
        if (request.getCategory() != null && request.getCategory().isAdminOnly()) {
            return admin(userId);
        }
        return user(userId);
    }
}
