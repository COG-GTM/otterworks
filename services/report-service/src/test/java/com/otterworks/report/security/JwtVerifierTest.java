package com.otterworks.report.security;

import org.junit.Test;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class JwtVerifierTest {

    private final JwtVerifier verifier = new JwtVerifier(TestJwt.SECRET);

    @Test
    public void acceptsValidAccessTokenForEveryHmacAlgorithm() {
        for (String alg : Arrays.asList("HS256", "HS384", "HS512")) {
            Optional<ReportCaller> caller = verifier.verify(TestJwt.sign(alg, claims("alice"), TestJwt.SECRET));
            assertTrue(alg, caller.isPresent());
            assertEquals("alice", caller.get().getUserId());
            assertFalse(caller.get().isAdmin());
        }
    }

    @Test
    public void readsAdminRole() {
        Optional<ReportCaller> caller = verifier.verify(TestJwt.accessToken("root", "USER", "ADMIN"));
        assertTrue(caller.isPresent());
        assertTrue(caller.get().isAdmin());
    }

    @Test
    public void fallsBackToUserIdClaim() {
        Map<String, Object> claims = claims("ignored");
        claims.remove("sub");
        claims.put("user_id", "bob");
        assertEquals("bob", verifier.verify(TestJwt.sign("HS256", claims, TestJwt.SECRET)).get().getUserId());
    }

    @Test
    public void rejectsWrongSecret() {
        assertFalse(verifier.verify(TestJwt.sign("HS256", claims("alice"), "some-other-secret-value")).isPresent());
    }

    @Test
    public void rejectsTamperedPayload() {
        String token = TestJwt.accessToken("alice");
        String[] parts = token.split("\\.");
        String forged = TestJwt.accessToken("mallory", "ADMIN").split("\\.")[1];
        assertFalse(verifier.verify(parts[0] + "." + forged + "." + parts[2]).isPresent());
    }

    @Test
    public void rejectsAlgNone() {
        assertFalse(verifier.verify(TestJwt.sign("none", claims("alice"), TestJwt.SECRET)).isPresent());
    }

    @Test
    public void rejectsExpiredAndMissingExpiry() {
        Map<String, Object> expired = claims("alice");
        expired.put("exp", System.currentTimeMillis() / 1000L - 10);
        assertFalse(verifier.verify(TestJwt.sign("HS256", expired, TestJwt.SECRET)).isPresent());

        Map<String, Object> noExp = claims("alice");
        noExp.remove("exp");
        assertFalse(verifier.verify(TestJwt.sign("HS256", noExp, TestJwt.SECRET)).isPresent());
    }

    @Test
    public void rejectsRefreshToken() {
        Map<String, Object> refresh = claims("alice");
        refresh.put("type", "refresh");
        assertFalse(verifier.verify(TestJwt.sign("HS256", refresh, TestJwt.SECRET)).isPresent());
    }

    @Test
    public void rejectsTokenWithoutSubject() {
        Map<String, Object> claims = claims("alice");
        claims.remove("sub");
        assertFalse(verifier.verify(TestJwt.sign("HS256", claims, TestJwt.SECRET)).isPresent());
    }

    @Test
    public void rejectsMalformedTokens() {
        assertFalse(verifier.verify("not-a-jwt").isPresent());
        assertFalse(verifier.verify("a.b.c").isPresent());
        assertFalse(verifier.verify("").isPresent());
        assertFalse(verifier.verify(null).isPresent());
    }

    @Test
    public void acceptsNothingWithoutSecret() {
        JwtVerifier unconfigured = new JwtVerifier("");
        assertFalse(unconfigured.isConfigured());
        assertFalse(unconfigured.verify(TestJwt.sign("HS256", claims("alice"), "any-secret")).isPresent());
    }

    private static Map<String, Object> claims(String sub) {
        Map<String, Object> claims = new LinkedHashMap<>();
        claims.put("sub", sub);
        claims.put("roles", Arrays.asList("USER"));
        claims.put("type", "access");
        claims.put("exp", System.currentTimeMillis() / 1000L + 600);
        return claims;
    }
}
