package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.otterworks.auth.entity.User;
import io.jsonwebtoken.JwtException;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class JwtTokenProviderTypeTest {

  private JwtTokenProvider provider;
  private User user;

  @BeforeEach
  void setUp() {
    provider =
        new JwtTokenProvider(
            "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac",
            3600,
            2592000); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
    user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("types@otterworks.dev");
    user.setDisplayName("Types User");
    user.setRoles(Set.of(User.Role.USER));
  }

  @Test
  void refreshTokenIsRejectedWhereAnAccessTokenIsExpected() {
    String refreshToken = provider.generateRefreshToken(user);

    assertThatThrownBy(() -> provider.validateTokenAndGetUserId(refreshToken))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token cannot be used as access token");
  }

  @Test
  void accessTokenIsRejectedWhereARefreshTokenIsExpected() {
    String accessToken = provider.generateAccessToken(user);

    assertThatThrownBy(() -> provider.validateRefreshTokenAndGetUserId(accessToken))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Token is not a refresh token");
  }

  @Test
  void refreshTokenValidationReturnsTheSubject() {
    String refreshToken = provider.generateRefreshToken(user);

    assertThat(provider.validateRefreshTokenAndGetUserId(refreshToken))
        .isEqualTo(user.getId().toString());
  }

  @Test
  void everyRefreshTokenGetsItsOwnJti() {
    String first = provider.extractJti(provider.generateRefreshToken(user));
    String second = provider.extractJti(provider.generateRefreshToken(user));

    assertThat(first).isNotEqualTo(second);
  }

  @Test
  void accessTokensCarryNoJti() {
    assertThat(provider.extractJti(provider.generateAccessToken(user))).isNull();
  }

  @Test
  void tokensSignedWithAnotherSecretFailValidation() {
    JwtTokenProvider foreign =
        new JwtTokenProvider(
            "another-jwt-secret-otterworks-that-is-also-at-least-32-bytes",
            3600,
            2592000); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
    String token = foreign.generateAccessToken(user);

    assertThatThrownBy(() -> provider.validateAndGetClaims(token)).isInstanceOf(JwtException.class);
    assertThat(provider.isTokenValid(token)).isFalse();
  }
}
