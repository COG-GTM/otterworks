package com.otterworks.legacyportal.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Mints auth-service-shaped HMAC JWTs for tests. */
public final class TestTokens {

    public static final String SECRET = "test-jwt-secret-legacy-portal-0123456789";

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private TestTokens() {}

    public static String accessToken(String subject) {
        return sign("HS256", SECRET, claims(subject, "access", Instant.now().plusSeconds(3600)));
    }

    public static Map<String, Object> claims(String subject, String type, Instant expiresAt) {
        Map<String, Object> claims = new LinkedHashMap<>();
        claims.put("sub", subject);
        claims.put("email", subject + "@example.com");
        claims.put("type", type);
        claims.put("iat", Instant.now().getEpochSecond());
        claims.put("exp", expiresAt.getEpochSecond());
        return claims;
    }

    public static String sign(String alg, String secret, Map<String, Object> claims) {
        try {
            String signingInput = segment(Map.of("alg", alg, "typ", "JWT")) + "." + segment(claims);
            String jcaName = "HmacSHA" + alg.substring(2);
            Mac mac = Mac.getInstance(jcaName);
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), jcaName));
            byte[] sig = mac.doFinal(signingInput.getBytes(StandardCharsets.US_ASCII));
            return signingInput + "." + Base64.getUrlEncoder().withoutPadding().encodeToString(sig);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    public static String segment(Map<String, ?> json) {
        try {
            return Base64.getUrlEncoder()
                    .withoutPadding()
                    .encodeToString(MAPPER.writeValueAsBytes(json));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
