package com.otterworks.legacyportal.security;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Clock;
import java.util.Base64;
import java.util.Map;
import java.util.Optional;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * Verifies the HMAC-signed access tokens issued by auth-service (shared {@code JWT_SECRET}).
 *
 * <p>Only HS256/HS384/HS512 are accepted. A token must carry a valid signature, an unexpired
 * {@code exp}, {@code type=access} and a well-formed {@code sub}; anything else is rejected. With
 * no secret (or one shorter than 32 bytes) configured, every token is rejected.
 */
public class JwtVerifier {

    static final int MIN_SECRET_BYTES = 32;

    /** Far above any auth-service token; bounds work done on untrusted input before verification. */
    static final int MAX_TOKEN_LENGTH = 4096;

    private static final Map<String, String> HMAC_ALGORITHMS =
            Map.of("HS256", "HmacSHA256", "HS384", "HmacSHA384", "HS512", "HmacSHA512");

    private final byte[] secret;
    private final ObjectMapper mapper;
    private final Clock clock;

    public JwtVerifier(String secret, ObjectMapper mapper, Clock clock) {
        byte[] bytes = secret == null ? new byte[0] : secret.getBytes(StandardCharsets.UTF_8);
        this.secret = bytes.length >= MIN_SECRET_BYTES ? bytes : null;
        this.mapper = mapper;
        this.clock = clock;
    }

    public boolean isConfigured() {
        return secret != null;
    }

    /** Returns the token's subject (user id) if the token is valid, otherwise empty. */
    public Optional<String> verifySubject(String token) {
        if (secret == null || token == null || token.length() > MAX_TOKEN_LENGTH) {
            return Optional.empty();
        }
        String[] parts = token.split("\\.", -1);
        if (parts.length != 3) {
            return Optional.empty();
        }
        try {
            JsonNode header = mapper.readTree(decode(parts[0]));
            if (header == null || !header.isObject()) {
                return Optional.empty();
            }
            String algorithm = HMAC_ALGORITHMS.get(header.path("alg").asText(""));
            if (algorithm == null) {
                return Optional.empty();
            }
            byte[] expected = sign(algorithm, parts[0] + "." + parts[1]);
            if (!MessageDigest.isEqual(expected, decode(parts[2]))) {
                return Optional.empty();
            }
            return subjectIfValid(mapper.readTree(decode(parts[1])));
        } catch (IllegalArgumentException | java.io.IOException | GeneralSecurityException e) {
            return Optional.empty();
        }
    }

    private Optional<String> subjectIfValid(JsonNode claims) {
        if (claims == null || !claims.isObject()) {
            return Optional.empty();
        }
        long now = clock.instant().getEpochSecond();
        JsonNode exp = claims.get("exp");
        if (exp == null || !exp.isNumber() || exp.asLong() <= now) {
            return Optional.empty();
        }
        JsonNode nbf = claims.get("nbf");
        if (nbf != null && (!nbf.isNumber() || nbf.asLong() > now)) {
            return Optional.empty();
        }
        if (!"access".equals(claims.path("type").asText(null))) {
            return Optional.empty();
        }
        JsonNode sub = claims.get("sub");
        if (sub == null || !sub.isTextual() || !UserIds.isValid(sub.asText())) {
            return Optional.empty();
        }
        return Optional.of(sub.asText());
    }

    private byte[] sign(String algorithm, String signingInput) throws GeneralSecurityException {
        Mac mac = Mac.getInstance(algorithm);
        mac.init(new SecretKeySpec(secret, algorithm));
        return mac.doFinal(signingInput.getBytes(StandardCharsets.US_ASCII));
    }

    private static byte[] decode(String part) {
        return Base64.getUrlDecoder().decode(part);
    }
}
