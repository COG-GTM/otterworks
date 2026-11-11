package com.otterworks.legacyportal.security;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Arrays;
import java.util.Date;

/** Mints tokens shaped like auth-service's access/refresh tokens for tests. */
public final class TestTokens {

    /** 51 bytes, so auth-service's jjwt would sign with HS384, as it does in docker-compose. */
    public static final String SECRET = "test-jwt-secret-for-legacy-portal-unit-tests-xyz12";

    private TestTokens() {
    }

    public static String bearer(String userId, String... roles) {
        return "Bearer " + sign(SECRET, JWSAlgorithm.HS384, claims(userId, "access", 3600, roles));
    }

    public static String signedWith(String secret, String userId) {
        return sign(secret, JWSAlgorithm.HS384, claims(userId, "access", 3600, "USER"));
    }

    public static String refresh(String userId) {
        return sign(SECRET, JWSAlgorithm.HS384, claims(userId, "refresh", 3600));
    }

    public static String expired(String userId) {
        return sign(SECRET, JWSAlgorithm.HS384, claims(userId, "access", -3600, "USER"));
    }

    private static JWTClaimsSet claims(String userId, String type, long ttlSeconds, String... roles) {
        Instant now = Instant.now();
        return new JWTClaimsSet.Builder()
                .subject(userId)
                .claim("type", type)
                .claim("roles", Arrays.asList(roles.length == 0 ? new String[] {"USER"} : roles))
                .issueTime(Date.from(now.minusSeconds(Math.max(0, -ttlSeconds) + 60)))
                .expirationTime(Date.from(now.plusSeconds(ttlSeconds)))
                .build();
    }

    private static String sign(String secret, JWSAlgorithm alg, JWTClaimsSet claims) {
        try {
            SignedJWT jwt = new SignedJWT(new JWSHeader(alg), claims);
            jwt.sign(new MACSigner(secret.getBytes(StandardCharsets.UTF_8)));
            return jwt.serialize();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
