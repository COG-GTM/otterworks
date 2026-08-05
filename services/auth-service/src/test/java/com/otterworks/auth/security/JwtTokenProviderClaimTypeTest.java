package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.otterworks.auth.entity.User;
import io.jsonwebtoken.JwtException;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class JwtTokenProviderClaimTypeTest {

  private static final String SECRET =
      "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac";

  private JwtTokenProvider provider;
  private User user;

  @BeforeEach
  void setUp() {
    provider = new JwtTokenProvider(SECRET, 3600, 2592000);
    user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("user@otterworks.dev");
    user.setDisplayName("User One");
    user.setRoles(Set.of(User.Role.USER));
  }

  @Test
  void validateRefreshTokenAndGetUserId_acceptsARefreshToken() {
    String refreshToken = provider.generateRefreshToken(user);

    assertThat(provider.validateRefreshTokenAndGetUserId(refreshToken))
        .isEqualTo(user.getId().toString());
  }

  @Test
  void validateRefreshTokenAndGetUserId_rejectsAnAccessToken() {
    String accessToken = provider.generateAccessToken(user);

    assertThatThrownBy(() -> provider.validateRefreshTokenAndGetUserId(accessToken))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Token is not a refresh token");
  }

  @Test
  void validateTokenAndGetUserId_rejectsARefreshToken() {
    String refreshToken = provider.generateRefreshToken(user);

    assertThatThrownBy(() -> provider.validateTokenAndGetUserId(refreshToken))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token cannot be used as access token");
  }

  @Test
  void everyRefreshTokenGetsItsOwnJti() {
    String first = provider.extractJti(provider.generateRefreshToken(user));
    String second = provider.extractJti(provider.generateRefreshToken(user));

    assertThat(first).isNotEqualTo(second);
  }

  @Test
  void anAccessTokenHasNoJti() {
    assertThat(provider.extractJti(provider.generateAccessToken(user))).isNull();
  }

  @Test
  void aTokenSignedWithAnotherSecretIsRejected() {
    JwtTokenProvider foreign =
        new JwtTokenProvider("a-completely-different-secret-that-is-long-enough-32", 3600, 2592000);
    String foreignToken = foreign.generateAccessToken(user);

    assertThat(provider.isTokenValid(foreignToken)).isFalse();
    assertThatThrownBy(() -> provider.validateAndGetClaims(foreignToken))
        .isInstanceOf(JwtException.class);
  }

  @Test
  void isTokenValid_rejectsBlankInput() {
    assertThat(provider.isTokenValid("")).isFalse();
  }

  @Test
  void anExpiredAccessTokenIsRejectedByEveryValidator() {
    JwtTokenProvider expiredProvider = new JwtTokenProvider(SECRET, -60, -60);
    String expired = expiredProvider.generateAccessToken(user);

    assertThat(expiredProvider.isTokenValid(expired)).isFalse();
    assertThatThrownBy(() -> expiredProvider.validateTokenAndGetUserId(expired))
        .isInstanceOf(JwtException.class);
  }
}
