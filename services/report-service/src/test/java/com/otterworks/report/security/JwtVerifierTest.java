package com.otterworks.report.security;

import org.junit.Test;

import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class JwtVerifierTest {

    private final JwtVerifier verifier = new JwtVerifier(TestTokens.SECRET);
    private final long future = System.currentTimeMillis() / 1000L + 600;

    @Test
    public void acceptsAccessTokenAndReadsSubjectAndRoles() {
        Optional<AuthenticatedUser> user = verifier.verify(TestTokens.accessToken("user-1", "USER", "ADMIN"));
        assertTrue(user.isPresent());
        assertEquals("user-1", user.get().getUserId());
        assertTrue(user.get().isAdmin());
    }

    @Test
    public void acceptsEveryHmacAlgorithmAuthServiceMayPick() {
        for (String alg : new String[] {"HS256", "HS384", "HS512"}) {
            String token = TestTokens.sign(alg, TestTokens.SECRET, TestTokens.claims("u", "access", future));
            assertTrue(alg, verifier.verify(token).isPresent());
        }
    }

    @Test
    public void fallsBackToUserIdClaim() {
        String token = TestTokens.sign("HS256", TestTokens.SECRET,
                "{\"user_id\":\"legacy-user\",\"type\":\"access\",\"exp\":" + future + "}");
        assertEquals("legacy-user", verifier.verify(token).get().getUserId());
    }

    @Test
    public void rejectsTokenSignedWithAnotherSecret() {
        String token = TestTokens.sign("HS256", "some-other-secret-that-is-long-enough-123",
                TestTokens.claims("u", "access", future));
        assertFalse(verifier.verify(token).isPresent());
    }

    @Test
    public void rejectsTamperedPayload() {
        String token = TestTokens.accessToken("victim");
        String[] parts = token.split("\\.");
        String forged = TestTokens.sign("HS256", TestTokens.SECRET, TestTokens.claims("attacker", "access", future, "ADMIN"))
                .split("\\.")[1];
        assertFalse(verifier.verify(parts[0] + "." + forged + "." + parts[2]).isPresent());
    }

    @Test
    public void rejectsUnsignedAndNonHmacTokens() {
        String claims = TestTokens.accessToken("u").split("\\.")[1];
        String none = java.util.Base64.getUrlEncoder().withoutPadding()
                .encodeToString("{\"alg\":\"none\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        assertFalse(verifier.verify(none + "." + claims + ".").isPresent());
        String rs = TestTokens.sign("HS256", TestTokens.SECRET, TestTokens.claims("u", "access", future));
        String rsHeader = java.util.Base64.getUrlEncoder().withoutPadding()
                .encodeToString("{\"alg\":\"RS256\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        assertFalse(verifier.verify(rsHeader + rs.substring(rs.indexOf('.'))).isPresent());
    }

    @Test
    public void rejectsExpiredMissingExpAndRefreshTokens() {
        long past = System.currentTimeMillis() / 1000L - 3600;
        assertFalse(verifier.verify(TestTokens.sign("HS256", TestTokens.SECRET,
                TestTokens.claims("u", "access", past))).isPresent());
        assertFalse(verifier.verify(TestTokens.sign("HS256", TestTokens.SECRET,
                "{\"sub\":\"u\"}")).isPresent());
        assertFalse(verifier.verify(TestTokens.sign("HS256", TestTokens.SECRET,
                TestTokens.claims("u", "refresh", future))).isPresent());
    }

    @Test
    public void rejectsTokenWithoutSubject() {
        assertFalse(verifier.verify(TestTokens.sign("HS256", TestTokens.SECRET,
                "{\"exp\":" + future + "}")).isPresent());
    }

    @Test
    public void rejectsGarbage() {
        assertFalse(verifier.verify("not-a-jwt").isPresent());
        assertFalse(verifier.verify("a.b.c").isPresent());
        assertFalse(verifier.verify("").isPresent());
        assertFalse(verifier.verify(null).isPresent());
    }

    @Test
    public void failsClosedWithoutUsableSecret() {
        String token = TestTokens.sign("HS256", TestTokens.SECRET, TestTokens.claims("u", "access", future));
        assertFalse(new JwtVerifier("").verify(token).isPresent());
        assertFalse(new JwtVerifier(null).verify(token).isPresent());
        String shortSecret = "short";
        assertFalse(new JwtVerifier(shortSecret)
                .verify(TestTokens.sign("HS256", shortSecret, TestTokens.claims("u", "access", future))).isPresent());
    }

    @Test
    public void rejectsEmptyOrNonObjectSegments() {
        assertFalse(verifier.verify(".e30.e30").isPresent());
        assertFalse(verifier.verify("e30..e30").isPresent());
        assertFalse(verifier.verify("WzFd.e30.e30").isPresent());
    }

    @Test
    public void rejectsTokensWithoutAccessType() {
        assertFalse(verifier.verify(TestTokens.sign("HS256", TestTokens.SECRET,
                TestTokens.claims("u", "", future))).isPresent());
        assertFalse(verifier.verify(TestTokens.sign("HS256", TestTokens.SECRET,
                TestTokens.claims("u", "password-reset", future))).isPresent());
    }
}
