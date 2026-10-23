package com.otterworks.legacyportal.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

class JwtAccessTokenVerifierTest {

    private final JwtAccessTokenVerifier verifier = new JwtAccessTokenVerifier(TestTokens.SECRET);

    @Test
    void refusesToStartWithoutASecret() {
        assertThatThrownBy(() -> new JwtAccessTokenVerifier(""))
                .isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> new JwtAccessTokenVerifier(null))
                .isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> new JwtAccessTokenVerifier("too-short-secret"))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void acceptsAuthServiceAccessToken() {
        String token = TestTokens.access(TestTokens.key(TestTokens.SECRET), "u-1", 60, "USER", "ADMIN");

        PortalPrincipal principal = verifier.verify(token).orElseThrow();

        assertThat(principal.getUserId()).isEqualTo("u-1");
        assertThat(principal.getRoles()).containsExactly("USER", "ADMIN");
        assertThat(principal.isAdmin()).isTrue();
    }

    @Test
    void rejectsRefreshExpiredForgedAndMalformedTokens() {
        assertThat(verifier.verify(TestTokens.refresh("u-1"))).isEmpty();
        assertThat(verifier.verify(TestTokens.access(TestTokens.key(TestTokens.SECRET), "u-1", -60)))
                .isEmpty();
        assertThat(
                        verifier.verify(
                                TestTokens.access(
                                        TestTokens.key("attacker-chosen-secret-that-is-at-least-32-bytes"),
                                        "u-1",
                                        60,
                                        "ADMIN")))
                .isEmpty();
        assertThat(verifier.verify("not.a.jwt")).isEmpty();
        assertThat(verifier.verify("")).isEmpty();
    }

    @Test
    void rejectsUnsignedToken() {
        String unsigned =
                io.jsonwebtoken.Jwts.builder().setSubject("u-1").claim("roles", "ADMIN").compact();

        assertThat(verifier.verify(unsigned)).isEmpty();
    }
}
