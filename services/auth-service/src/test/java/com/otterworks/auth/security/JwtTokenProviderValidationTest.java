package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.otterworks.auth.entity.User;
import io.jsonwebtoken.JwtException;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Covers the token-type guards of {@link JwtTokenProvider}. */
class JwtTokenProviderValidationTest {

  private JwtTokenProvider tokenProvider;
  private User user;

  @BeforeEach
  void setUp() {
    tokenProvider =
        new JwtTokenProvider(
            "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac",
            3600,
            2592000); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
    user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("guard@otterworks.dev");
    user.setDisplayName("Guard User");
    user.setRoles(Set.of(User.Role.USER));
  }

  @Test
  void validateTokenAndGetUserId_shouldRejectRefreshToken() {
    String refreshToken = tokenProvider.generateRefreshToken(user);

    assertThatThrownBy(() -> tokenProvider.validateTokenAndGetUserId(refreshToken))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token cannot be used as access token");
  }

  @Test
  void validateRefreshTokenAndGetUserId_shouldRejectAccessToken() {
    String accessToken = tokenProvider.generateAccessToken(user);

    assertThatThrownBy(() -> tokenProvider.validateRefreshTokenAndGetUserId(accessToken))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Token is not a refresh token");
  }

  @Test
  void validateRefreshTokenAndGetUserId_shouldReturnSubjectForRefreshToken() {
    String refreshToken = tokenProvider.generateRefreshToken(user);

    assertThat(tokenProvider.validateRefreshTokenAndGetUserId(refreshToken))
        .isEqualTo(user.getId().toString());
  }

  @Test
  void validateAndGetClaims_shouldRejectTokenSignedWithAnotherKey() {
    JwtTokenProvider foreignProvider =
        new JwtTokenProvider(
            "another-secret-that-is-also-long-enough-for-hmac-sha-256-ok",
            3600,
            2592000); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
    String foreignToken = foreignProvider.generateAccessToken(user);

    assertThatThrownBy(() -> tokenProvider.validateAndGetClaims(foreignToken))
        .isInstanceOf(JwtException.class);
    assertThat(tokenProvider.isTokenValid(foreignToken)).isFalse();
  }

  @Test
  void extractJti_shouldBeNullForAccessTokens() {
    String accessToken = tokenProvider.generateAccessToken(user);

    assertThat(tokenProvider.extractJti(accessToken)).isNull();
  }

  @Test
  void generateRefreshToken_shouldIssueAUniqueJtiPerCall() {
    String first = tokenProvider.extractJti(tokenProvider.generateRefreshToken(user));
    String second = tokenProvider.extractJti(tokenProvider.generateRefreshToken(user));

    assertThat(first).isNotBlank().isNotEqualTo(second);
  }
}
