package com.otterworks.report.security;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

/**
 * Builds HMAC-signed JWTs shaped like the ones auth-service issues.
 */
public final class TestTokens {

    /** Must match otterworks.jwt.secret in application-test.properties. */
    public static final String SECRET = "report-service-test-secret-that-is-long-enough-for-hs384";

    private TestTokens() {
    }

    public static String bearer(String userId, String... roles) {
        return "Bearer " + token(SECRET, "HS384", userId, "access",
                System.currentTimeMillis() / 1000 + 3600, roles);
    }

    public static String token(String secret, String alg, String userId, String type, long exp, String... roles) {
        StringBuilder roleJson = new StringBuilder("[");
        for (int i = 0; i < roles.length; i++) {
            roleJson.append(i > 0 ? "," : "").append('"').append(roles[i]).append('"');
        }
        roleJson.append(']');
        String header = "{\"alg\":\"" + alg + "\"}";
        String payload = "{\"sub\":\"" + userId + "\",\"roles\":" + roleJson
                + ",\"type\":\"" + type + "\",\"exp\":" + exp + "}";
        String signingInput = encode(header) + "." + encode(payload);
        return signingInput + "." + sign(secret, alg, signingInput);
    }

    private static String encode(String json) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(json.getBytes(StandardCharsets.UTF_8));
    }

    private static String sign(String secret, String alg, String input) {
        if ("none".equals(alg)) {
            return "";
        }
        try {
            String macAlg = "HmacSHA" + alg.substring(2);
            Mac mac = Mac.getInstance(macAlg);
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), macAlg));
            return Base64.getUrlEncoder().withoutPadding()
                    .encodeToString(mac.doFinal(input.getBytes(StandardCharsets.US_ASCII)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
