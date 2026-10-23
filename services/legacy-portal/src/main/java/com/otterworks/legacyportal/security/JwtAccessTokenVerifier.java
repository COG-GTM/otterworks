package com.otterworks.legacyportal.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Optional;
import java.util.Set;
import javax.crypto.SecretKey;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Verifies the HMAC-signed (HS256/HS384/HS512) access tokens auth-service issues, using the
 * shared {@code JWT_SECRET}.
 * Only {@code type: access} tokens with a subject and an unexpired {@code exp} are accepted.
 */
@Component
public class JwtAccessTokenVerifier {

    static final int MIN_SECRET_BYTES = 32;

    private final SecretKey key;

    public JwtAccessTokenVerifier(@Value("${portal.security.jwt-secret:}") String secret) {
        byte[] bytes = secret == null ? new byte[0] : secret.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < MIN_SECRET_BYTES) {
            throw new IllegalStateException(
                    "JWT_SECRET (portal.security.jwt-secret) must be set to the auth-service signing"
                            + " secret and be at least " + MIN_SECRET_BYTES + " bytes");
        }
        this.key = Keys.hmacShaKeyFor(bytes);
    }

    public Optional<PortalPrincipal> verify(String token) {
        Claims claims;
        try {
            claims = Jwts.parserBuilder().setSigningKey(key).build().parseClaimsJws(token).getBody();
        } catch (JwtException | IllegalArgumentException e) {
            return Optional.empty();
        }
        if (!"access".equals(claims.get("type")) || claims.getExpiration() == null) {
            return Optional.empty();
        }
        String subject = claims.getSubject();
        if (subject == null || subject.isBlank()) {
            return Optional.empty();
        }
        return Optional.of(new PortalPrincipal(subject, roles(claims.get("roles"))));
    }

    private static Set<String> roles(Object claim) {
        Set<String> roles = new LinkedHashSet<>();
        if (claim instanceof Collection) {
            for (Object role : (Collection<?>) claim) {
                if (role instanceof String) {
                    roles.add((String) role);
                }
            }
        }
        return roles;
    }
}
