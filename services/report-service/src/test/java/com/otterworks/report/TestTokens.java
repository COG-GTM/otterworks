package com.otterworks.report;

import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Date;

/**
 * Mints tokens shaped like auth-service access tokens, signed with the test profile's secret.
 */
public final class TestTokens {

    public static final String SECRET = "report-service-test-jwt-secret-0123456789-abcdefghij";

    private TestTokens() {
    }

    public static String bearer(String userId, String... roles) {
        return "Bearer " + sign(SECRET, claims(userId, "access", 3600, roles));
    }

    public static String expired(String userId) {
        return "Bearer " + sign(SECRET, claims(userId, "access", -3600));
    }

    public static String refresh(String userId) {
        return "Bearer " + sign(SECRET, claims(userId, "refresh", 3600));
    }

    public static String wrongSecret(String userId, String... roles) {
        return "Bearer " + sign("some-other-secret-that-auth-service-never-used-xyz", claims(userId, "access", 3600, roles));
    }

    private static JWTClaimsSet claims(String userId, String type, long ttlSeconds, String... roles) {
        long now = System.currentTimeMillis();
        return new JWTClaimsSet.Builder()
                .subject(userId)
                .claim("email", userId + "@example.com")
                .claim("roles", Arrays.asList(roles.length == 0 ? new String[]{"USER"} : roles))
                .claim("type", type)
                .issueTime(new Date(now - 60_000L))
                .expirationTime(new Date(now + ttlSeconds * 1000L))
                .build();
    }

    private static String sign(String secret, JWTClaimsSet claims) {
        try {
            SignedJWT jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.HS384), claims);
            jwt.sign(new MACSigner(secret.getBytes(StandardCharsets.UTF_8)));
            return jwt.serialize();
        } catch (JOSEException e) {
            throw new IllegalStateException(e);
        }
    }
}
