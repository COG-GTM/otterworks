package com.otterworks.report.security;

import com.fasterxml.jackson.databind.ObjectMapper;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Base64;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Mints HMAC JWTs shaped like auth-service access tokens for tests.
 */
public final class TestJwt {

    /** Must match {@code otterworks.security.jwt-secret} in application-test.properties. */
    public static final String SECRET = "report-service-test-jwt-secret-0123456789abcdef";

    private TestJwt() {
    }

    public static String bearer(String userId, String... roles) {
        return "Bearer " + accessToken(userId, roles);
    }

    public static String adminBearer(String userId) {
        return bearer(userId, "USER", "ADMIN");
    }

    public static String accessToken(String userId, String... roles) {
        Map<String, Object> claims = new LinkedHashMap<>();
        claims.put("sub", userId);
        claims.put("roles", roles.length == 0 ? Arrays.asList("USER") : Arrays.asList(roles));
        claims.put("type", "access");
        long now = System.currentTimeMillis() / 1000L;
        claims.put("iat", now);
        claims.put("exp", now + 3600);
        return sign("HS384", claims, SECRET);
    }

    public static String sign(String alg, Map<String, Object> claims, String secret) {
        Map<String, Object> header = new HashMap<>();
        header.put("alg", alg);
        header.put("typ", "JWT");
        String signingInput = encodeJson(header) + "." + encodeJson(claims);
        if ("none".equals(alg)) {
            return signingInput + ".";
        }
        try {
            String jca = "Hmac" + alg.replace("HS", "SHA");
            Mac mac = Mac.getInstance(jca);
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), jca));
            byte[] signature = mac.doFinal(signingInput.getBytes(StandardCharsets.US_ASCII));
            return signingInput + "." + Base64.getUrlEncoder().withoutPadding().encodeToString(signature);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static String encodeJson(Map<String, Object> value) {
        try {
            byte[] json = new ObjectMapper().writeValueAsBytes(value);
            return Base64.getUrlEncoder().withoutPadding().encodeToString(json);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
