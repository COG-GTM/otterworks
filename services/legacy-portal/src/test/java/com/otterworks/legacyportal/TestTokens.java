package com.otterworks.legacyportal;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.List;

/** Mints tokens shaped like auth-service's (jjwt picks HS384 for this 51-byte secret). */
public final class TestTokens {

    public static final String SECRET = "test-jwt-secret-legacy-portal-0123456789abcdefghijk";

    private TestTokens() {}

    public static String access(String userId, String... roles) {
        return sign(SECRET, JWSAlgorithm.HS384, userId, "access", List.of(roles), 3600);
    }

    public static String sign(
            String secret,
            JWSAlgorithm algorithm,
            String userId,
            String type,
            List<String> roles,
            long ttlSeconds) {
        try {
            Instant now = Instant.now();
            JWTClaimsSet claims =
                    new JWTClaimsSet.Builder()
                            .subject(userId)
                            .claim("roles", roles)
                            .claim("type", type)
                            .issueTime(Date.from(now))
                            .expirationTime(Date.from(now.plusSeconds(ttlSeconds)))
                            .build();
            SignedJWT jwt = new SignedJWT(new JWSHeader(algorithm), claims);
            jwt.sign(new MACSigner(secret.getBytes(StandardCharsets.UTF_8)));
            return jwt.serialize();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
