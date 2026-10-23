package com.otterworks.report.security;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

/**
 * Mints HMAC JWTs shaped like auth-service access tokens for tests.
 */
public final class TestTokens {

    /** Matches otterworks.security.jwt-secret in application-test.properties. */
    public static final String SECRET = "report-service-test-secret-0123456789abcdef";

    private TestTokens() {
    }

    public static String accessToken(String userId, String... roles) {
        return sign("HS256", SECRET, claims(userId, "access", System.currentTimeMillis() / 1000L + 3600, roles));
    }

    public static String bearer(String userId, String... roles) {
        return "Bearer " + accessToken(userId, roles);
    }

    public static String claims(String userId, String type, long exp, String... roles) {
        StringBuilder roleJson = new StringBuilder("[");
        for (int i = 0; i < roles.length; i++) {
            if (i > 0) {
                roleJson.append(',');
            }
            roleJson.append('"').append(roles[i]).append('"');
        }
        roleJson.append(']');
        return "{\"sub\":\"" + userId + "\",\"type\":\"" + type + "\",\"roles\":" + roleJson
                + ",\"exp\":" + exp + "}";
    }

    public static String sign(String alg, String secret, String claimsJson) {
        String header = encode("{\"alg\":\"" + alg + "\",\"typ\":\"JWT\"}");
        String payload = encode(claimsJson);
        String signingInput = header + "." + payload;
        String macAlg = "Hmac" + alg.replace("HS", "SHA");
        try {
            Mac mac = Mac.getInstance(macAlg);
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), macAlg));
            byte[] sig = mac.doFinal(signingInput.getBytes(StandardCharsets.US_ASCII));
            return signingInput + "." + Base64.getUrlEncoder().withoutPadding().encodeToString(sig);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static String encode(String json) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(json.getBytes(StandardCharsets.UTF_8));
    }
}
