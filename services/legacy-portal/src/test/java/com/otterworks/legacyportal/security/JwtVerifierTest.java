package com.otterworks.legacyportal.security;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;

class JwtVerifierTest {

    private static final String USER = "6f1c2a9e-3b4d-4c5e-9f00-112233445566";

    private final JwtVerifier verifier =
            new JwtVerifier(TestTokens.SECRET, new ObjectMapper(), Clock.systemUTC());

    private static Map<String, Object> validClaims() {
        return TestTokens.claims(USER, "access", Instant.now().plusSeconds(600));
    }

    @Test
    void acceptsValidAccessTokensForEveryHmacAlgorithm() {
        for (String alg : new String[] {"HS256", "HS384", "HS512"}) {
            String token = TestTokens.sign(alg, TestTokens.SECRET, validClaims());
            assertThat(verifier.verifySubject(token)).contains(USER);
        }
    }

    @Test
    void rejectsTokenSignedWithAnotherSecret() {
        String token = TestTokens.sign("HS256", "some-other-secret-that-is-long-enough!!", validClaims());
        assertThat(verifier.verifySubject(token)).isEmpty();
    }

    @Test
    void rejectsTamperedPayload() {
        String token = TestTokens.sign("HS256", TestTokens.SECRET, validClaims());
        String[] parts = token.split("\\.");
        String forged =
                parts[0]
                        + "."
                        + TestTokens.segment(
                                TestTokens.claims("victim", "access", Instant.now().plusSeconds(600)))
                        + "."
                        + parts[2];
        assertThat(verifier.verifySubject(forged)).isEmpty();
    }

    @Test
    void rejectsUnsignedAndNonHmacAlgorithms() {
        String payload = TestTokens.segment(validClaims());
        assertThat(verifier.verifySubject(TestTokens.segment(Map.of("alg", "none")) + "." + payload + "."))
                .isEmpty();
        String rs256 = TestTokens.sign("HS256", TestTokens.SECRET, validClaims());
        String[] parts = rs256.split("\\.");
        String relabelled = TestTokens.segment(Map.of("alg", "RS256")) + "." + parts[1] + "." + parts[2];
        assertThat(verifier.verifySubject(relabelled)).isEmpty();
    }

    @Test
    void rejectsExpiredOrNonExpiringTokens() {
        String expired =
                TestTokens.sign(
                        "HS256",
                        TestTokens.SECRET,
                        TestTokens.claims(USER, "access", Instant.now().minusSeconds(1)));
        assertThat(verifier.verifySubject(expired)).isEmpty();

        Map<String, Object> noExp = validClaims();
        noExp.remove("exp");
        assertThat(verifier.verifySubject(TestTokens.sign("HS256", TestTokens.SECRET, noExp))).isEmpty();
    }

    @Test
    void rejectsNotYetValidTokens() {
        Map<String, Object> claims = validClaims();
        claims.put("nbf", Instant.now().plusSeconds(300).getEpochSecond());
        assertThat(verifier.verifySubject(TestTokens.sign("HS256", TestTokens.SECRET, claims))).isEmpty();
    }

    @Test
    void rejectsRefreshTokensAndTokensWithoutType() {
        String refresh =
                TestTokens.sign(
                        "HS256",
                        TestTokens.SECRET,
                        TestTokens.claims(USER, "refresh", Instant.now().plusSeconds(600)));
        assertThat(verifier.verifySubject(refresh)).isEmpty();

        Map<String, Object> untyped = validClaims();
        untyped.remove("type");
        assertThat(verifier.verifySubject(TestTokens.sign("HS256", TestTokens.SECRET, untyped))).isEmpty();
    }

    @Test
    void rejectsMissingOrMalformedSubject() {
        Map<String, Object> noSub = validClaims();
        noSub.remove("sub");
        assertThat(verifier.verifySubject(TestTokens.sign("HS256", TestTokens.SECRET, noSub))).isEmpty();

        Map<String, Object> badSub = validClaims();
        badSub.put("sub", "../admin");
        assertThat(verifier.verifySubject(TestTokens.sign("HS256", TestTokens.SECRET, badSub))).isEmpty();
    }

    @Test
    void rejectsMalformedTokens() {
        assertThat(verifier.verifySubject(null)).isEmpty();
        assertThat(verifier.verifySubject("")).isEmpty();
        assertThat(verifier.verifySubject("a.b")).isEmpty();
        assertThat(verifier.verifySubject("!!!.@@@.###")).isEmpty();
        assertThat(verifier.verifySubject("e30.e30.e30.e30")).isEmpty();
    }

    @Test
    void rejectsEverythingWhenSecretMissingOrTooShort() {
        String token = TestTokens.sign("HS256", TestTokens.SECRET, validClaims());

        JwtVerifier unset = new JwtVerifier("", new ObjectMapper(), Clock.systemUTC());
        assertThat(unset.isConfigured()).isFalse();
        assertThat(unset.verifySubject(token)).isEmpty();

        String shortSecret = "too-short";
        JwtVerifier weak = new JwtVerifier(shortSecret, new ObjectMapper(), Clock.systemUTC());
        assertThat(weak.isConfigured()).isFalse();
        assertThat(weak.verifySubject(TestTokens.sign("HS256", shortSecret, validClaims()))).isEmpty();
    }

    @Test
    void rejectsEmptyOrNonObjectSegments() {
        assertThat(verifier.verifySubject("..")).isEmpty();
        assertThat(verifier.verifySubject("W10..")).isEmpty();
        assertThat(verifier.verifySubject("bnVsbA..")).isEmpty();
        String header = TestTokens.segment(Map.of("alg", "HS256"));
        assertThat(verifier.verifySubject(TestTokens.signRaw("HS256", TestTokens.SECRET, header, "")))
                .isEmpty();
        assertThat(
                        verifier.verifySubject(
                                TestTokens.signRaw("HS256", TestTokens.SECRET, header, "W10")))
                .isEmpty();
    }

    @Test
    void rejectsOversizedTokens() {
        Map<String, Object> claims = new java.util.HashMap<>(validClaims());
        claims.put("pad", "x".repeat(JwtVerifier.MAX_TOKEN_LENGTH));
        assertThat(verifier.verifySubject(TestTokens.sign("HS256", TestTokens.SECRET, claims))).isEmpty();
    }
}
