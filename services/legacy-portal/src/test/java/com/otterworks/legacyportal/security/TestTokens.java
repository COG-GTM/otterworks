package com.otterworks.legacyportal.security;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import java.util.List;
import java.util.stream.Collectors;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Builds auth-service-shaped HMAC access tokens for tests. */
public final class TestTokens {

    public static final String SECRET = "legacy-portal-test-secret-at-least-32-bytes";

    private TestTokens() {}

    public static String bearer(String subject, String... roles) {
        return "Bearer " + access(subject, roles);
    }

    public static String access(String subject, String... roles) {
        return sign(SECRET, "HS256", claims(subject, "access", Instant.now().plusSeconds(900), roles));
    }

    static String claims(String subject, String type, Instant exp, String... roles) {
        String roleJson =
                List.of(roles).stream().map(r -> "\"" + r + "\"").collect(Collectors.joining(","));
        return "{\"sub\":\"" + subject + "\",\"type\":\"" + type + "\",\"exp\":"
                + exp.getEpochSecond() + ",\"roles\":[" + roleJson + "]}";
    }

    static String sign(String secret, String alg, String claimsJson) {
        String header = encode("{\"alg\":\"" + alg + "\",\"typ\":\"JWT\"}");
        String payload = encode(claimsJson);
        String javaAlg = "Hmac" + alg.replace("HS", "SHA");
        try {
            Mac mac = Mac.getInstance(javaAlg);
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), javaAlg));
            byte[] sig =
                    mac.doFinal((header + "." + payload).getBytes(StandardCharsets.US_ASCII));
            return header + "." + payload + "." + Base64.getUrlEncoder().withoutPadding().encodeToString(sig);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    static String encode(String json) {
        return Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString(json.getBytes(StandardCharsets.UTF_8));
    }
}
