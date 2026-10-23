package com.otterworks.legacyportal.security;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Instant;
import org.junit.jupiter.api.Test;

class JwtVerifierTest {

    private final JwtVerifier verifier =
            new JwtVerifier(TestTokens.SECRET, new ObjectMapper(), Clock.systemUTC());

    private static String token(String claims) {
        return TestTokens.sign(TestTokens.SECRET, "HS256", claims);
    }

    @Test
    void acceptsValidAccessTokenAndReadsRoles() {
        JwtVerifier.VerifiedToken token =
                verifier.verify(TestTokens.access("user-1", "USER", "ADMIN")).orElseThrow();

        assertThat(token.getSubject()).isEqualTo("user-1");
        assertThat(token.getRoles()).containsExactly("USER", "ADMIN");
    }

    @Test
    void acceptsHs512() {
        String claims =
                TestTokens.claims("user-1", "access", Instant.now().plusSeconds(60), "OWNER");
        assertThat(verifier.verify(TestTokens.sign(TestTokens.SECRET, "HS512", claims)))
                .hasValueSatisfying(t -> assertThat(t.getRoles()).containsExactly("OWNER"));
    }

    @Test
    void rejectsTokenSignedWithAnotherSecret() {
        String claims =
                TestTokens.claims("user-1", "access", Instant.now().plusSeconds(60), "ADMIN");
        String forged = TestTokens.sign("some-other-secret-that-is-at-least-32-bytes", "HS256", claims);
        assertThat(verifier.verify(forged)).isEmpty();
    }

    @Test
    void rejectsUnsignedAlgNoneToken() {
        String claims =
                TestTokens.claims("user-1", "access", Instant.now().plusSeconds(60), "ADMIN");
        String none =
                TestTokens.encode("{\"alg\":\"none\"}") + "." + TestTokens.encode(claims) + ".";
        assertThat(verifier.verify(none)).isEmpty();
    }

    @Test
    void rejectsTamperedRoles() {
        String valid = TestTokens.access("user-1", "USER");
        String[] parts = valid.split("\\.");
        String elevated =
                TestTokens.encode(
                        TestTokens.claims("user-1", "access", Instant.now().plusSeconds(900), "ADMIN"));
        assertThat(verifier.verify(parts[0] + "." + elevated + "." + parts[2])).isEmpty();
    }

    @Test
    void rejectsExpiredToken() {
        assertThat(
                        verifier.verify(
                                token(
                                        TestTokens.claims(
                                                "user-1", "access", Instant.now().minusSeconds(1), "ADMIN"))))
                .isEmpty();
    }

    @Test
    void rejectsRefreshToken() {
        assertThat(
                        verifier.verify(
                                token(
                                        TestTokens.claims(
                                                "user-1", "refresh", Instant.now().plusSeconds(60), "ADMIN"))))
                .isEmpty();
    }

    @Test
    void rejectsMissingOrMalformedSubject() {
        long exp = Instant.now().plusSeconds(60).getEpochSecond();
        assertThat(verifier.verify(token("{\"type\":\"access\",\"exp\":" + exp + "}"))).isEmpty();
        assertThat(
                        verifier.verify(
                                token("{\"sub\":\"a b\",\"type\":\"access\",\"exp\":" + exp + "}")))
                .isEmpty();
    }

    @Test
    void ignoresMalformedRoleEntries() {
        long exp = Instant.now().plusSeconds(60).getEpochSecond();
        String claims =
                "{\"sub\":\"u1\",\"type\":\"access\",\"exp\":" + exp
                        + ",\"roles\":[\"ADMIN \",\"admin\",{\"r\":1},\"EDITOR\"]}";
        assertThat(verifier.verify(token(claims)))
                .hasValueSatisfying(t -> assertThat(t.getRoles()).containsExactly("EDITOR"));
        String scalar = "{\"sub\":\"u1\",\"type\":\"access\",\"exp\":" + exp + ",\"roles\":\"ADMIN\"}";
        assertThat(verifier.verify(token(scalar)))
                .hasValueSatisfying(t -> assertThat(t.getRoles()).isEmpty());
    }

    @Test
    void rejectsGarbageAndOversizedInput() {
        assertThat(verifier.verify(null)).isEmpty();
        assertThat(verifier.verify("not-a-jwt")).isEmpty();
        assertThat(verifier.verify("a.b.c")).isEmpty();
        assertThat(verifier.verify("x".repeat(JwtVerifier.MAX_TOKEN_LENGTH + 1))).isEmpty();
    }

    @Test
    void rejectsEverythingWithoutAStrongSecret() {
        String valid = TestTokens.access("user-1", "ADMIN");
        JwtVerifier unset = new JwtVerifier("", new ObjectMapper(), Clock.systemUTC());
        JwtVerifier weak = new JwtVerifier("short", new ObjectMapper(), Clock.systemUTC());

        assertThat(unset.isConfigured()).isFalse();
        assertThat(unset.verify(valid)).isEmpty();
        assertThat(weak.isConfigured()).isFalse();
        assertThat(weak.verify(valid)).isEmpty();
    }
}
