package com.otterworks.report.security;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Verifies the HMAC-signed access tokens issued by auth-service (same JWT_SECRET
 * the api-gateway uses). The service validates tokens itself because it is also
 * reachable without passing through the gateway.
 *
 * Fails closed: with no secret configured, or one shorter than 256 bits, every
 * token is rejected.
 */
@Component
public class JwtVerifier {

    private static final Logger logger = LoggerFactory.getLogger(JwtVerifier.class);

    static final int MIN_SECRET_BYTES = 32;
    private static final long CLOCK_SKEW_SECONDS = 30;
    private static final Map<String, String> HMAC_ALGORITHMS = new HashMap<>();

    static {
        HMAC_ALGORITHMS.put("HS256", "HmacSHA256");
        HMAC_ALGORITHMS.put("HS384", "HmacSHA384");
        HMAC_ALGORITHMS.put("HS512", "HmacSHA512");
    }

    private final byte[] secret;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public JwtVerifier(@Value("${otterworks.security.jwt-secret:}") String secret) {
        byte[] bytes = secret == null ? new byte[0] : secret.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < MIN_SECRET_BYTES) {
            logger.error("JWT_SECRET is unset or shorter than {} bytes; all /api/v1/reports requests will be rejected",
                    MIN_SECRET_BYTES);
            this.secret = null;
        } else {
            this.secret = bytes;
        }
    }

    public Optional<AuthenticatedUser> verify(String token) {
        if (secret == null || token == null) {
            return Optional.empty();
        }
        String[] parts = token.split("\\.", -1);
        if (parts.length != 3) {
            return Optional.empty();
        }
        try {
            JsonNode header = objectMapper.readTree(decode(parts[0]));
            if (header == null || !header.isObject()) {
                return Optional.empty();
            }
            String macAlgorithm = HMAC_ALGORITHMS.get(header.path("alg").asText(""));
            if (macAlgorithm == null) {
                return Optional.empty();
            }

            Mac mac = Mac.getInstance(macAlgorithm);
            mac.init(new SecretKeySpec(secret, macAlgorithm));
            byte[] expected = mac.doFinal((parts[0] + "." + parts[1]).getBytes(StandardCharsets.US_ASCII));
            if (!MessageDigest.isEqual(expected, decode(parts[2]))) {
                return Optional.empty();
            }

            JsonNode claims = objectMapper.readTree(decode(parts[1]));
            if (claims == null || !claims.isObject()) {
                return Optional.empty();
            }
            long now = System.currentTimeMillis() / 1000L;
            JsonNode exp = claims.get("exp");
            if (exp == null || !exp.canConvertToLong() || exp.asLong() + CLOCK_SKEW_SECONDS < now) {
                return Optional.empty();
            }
            JsonNode nbf = claims.get("nbf");
            if (nbf != null && (!nbf.canConvertToLong() || nbf.asLong() - CLOCK_SKEW_SECONDS > now)) {
                return Optional.empty();
            }
            if (!"access".equals(claims.path("type").asText(""))) {
                return Optional.empty();
            }

            String userId = claims.path("sub").asText("");
            if (userId.trim().isEmpty()) {
                userId = claims.path("user_id").asText("");
            }
            if (userId.trim().isEmpty()) {
                return Optional.empty();
            }

            Set<String> roles = new LinkedHashSet<>();
            JsonNode roleClaims = claims.get("roles");
            if (roleClaims != null && roleClaims.isArray()) {
                for (JsonNode role : roleClaims) {
                    if (role.isTextual()) {
                        roles.add(role.asText());
                    }
                }
            }
            return Optional.of(new AuthenticatedUser(userId, roles));
        } catch (IllegalArgumentException | java.io.IOException | GeneralSecurityException e) {
            return Optional.empty();
        }
    }

    private static byte[] decode(String segment) {
        return Base64.getUrlDecoder().decode(segment);
    }
}
