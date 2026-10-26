package com.otterworks.report.security;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Verifies the HMAC-signed access tokens issued by auth-service (the same tokens the
 * API gateway validates) and extracts the caller identity from them.
 *
 * A token is accepted only when its signature matches the shared JWT secret, its
 * algorithm is HS256/HS384/HS512, it carries an unexpired {@code exp}, and it is not
 * a refresh token. With no secret configured nothing is accepted.
 */
public class JwtVerifier {

    private static final Map<String, String> HMAC_ALGORITHMS;

    static {
        Map<String, String> algorithms = new HashMap<>();
        algorithms.put("HS256", "HmacSHA256");
        algorithms.put("HS384", "HmacSHA384");
        algorithms.put("HS512", "HmacSHA512");
        HMAC_ALGORITHMS = Collections.unmodifiableMap(algorithms);
    }

    private final byte[] secret;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public JwtVerifier(String secret) {
        this.secret = secret == null ? new byte[0] : secret.getBytes(StandardCharsets.UTF_8);
    }

    public boolean isConfigured() {
        return secret.length > 0;
    }

    public Optional<ReportCaller> verify(String token) {
        if (!isConfigured() || token == null) {
            return Optional.empty();
        }
        String[] parts = token.split("\\.", -1);
        if (parts.length != 3) {
            return Optional.empty();
        }
        try {
            JsonNode header = decodeJson(parts[0]);
            String jcaAlgorithm = HMAC_ALGORITHMS.get(header.path("alg").asText(""));
            if (jcaAlgorithm == null) {
                return Optional.empty();
            }

            Mac mac = Mac.getInstance(jcaAlgorithm);
            mac.init(new SecretKeySpec(secret, jcaAlgorithm));
            byte[] expected = mac.doFinal((parts[0] + "." + parts[1]).getBytes(StandardCharsets.US_ASCII));
            byte[] actual = Base64.getUrlDecoder().decode(parts[2]);
            if (!MessageDigest.isEqual(expected, actual)) {
                return Optional.empty();
            }

            JsonNode claims = decodeJson(parts[1]);
            long nowSeconds = System.currentTimeMillis() / 1000L;
            JsonNode exp = claims.get("exp");
            if (exp == null || !exp.isNumber() || exp.asLong() <= nowSeconds) {
                return Optional.empty();
            }
            JsonNode nbf = claims.get("nbf");
            if (nbf != null && nbf.isNumber() && nbf.asLong() > nowSeconds) {
                return Optional.empty();
            }
            if ("refresh".equals(claims.path("type").asText(null))) {
                return Optional.empty();
            }

            String userId = claims.path("sub").asText("");
            if (userId.isEmpty()) {
                userId = claims.path("user_id").asText("");
            }
            if (userId.isEmpty()) {
                return Optional.empty();
            }

            List<String> roles = new ArrayList<>();
            JsonNode rolesNode = claims.get("roles");
            if (rolesNode != null && rolesNode.isArray()) {
                for (JsonNode role : rolesNode) {
                    if (role.isTextual()) {
                        roles.add(role.asText());
                    }
                }
            }
            return Optional.of(new ReportCaller(userId, roles));
        } catch (IllegalArgumentException | GeneralSecurityException | java.io.IOException e) {
            return Optional.empty();
        }
    }

    private JsonNode decodeJson(String segment) throws java.io.IOException {
        JsonNode node = objectMapper.readTree(Base64.getUrlDecoder().decode(segment));
        if (node == null || !node.isObject()) {
            throw new IllegalArgumentException("JWT segment is not a JSON object");
        }
        return node;
    }
}
