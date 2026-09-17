package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.otterworks.auth.entity.User;
import io.jsonwebtoken.security.SignatureException;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class JwtTokenProviderValidationTest {

  private static final String SECRET =
      "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac";
  private static final String OTHER_SECRET =
      "another-jwt-secret-otterworks-also-at-least-32-bytes-long-for-hmac";

  private JwtTokenProvider provider;
  private User user;

  @BeforeEach
  void setUp() {
    provider = new JwtTokenProvider(SECRET, 3600, 2592000);
    user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("validation@otterworks.dev");
    user.setDisplayName("Validation User");
    user.setRoles(Set.of(User.Role.USER));
  }

  @Test
  void validateTokenAndGetUserId_shouldRejectARefreshToken() {
    String refreshToken = provider.generateRefreshToken(user);

    assertThatThrownBy(() -> provider.validateTokenAndGetUserId(refreshToken))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token cannot be used as access token");
  }

  @Test
  void validateRefreshTokenAndGetUserId_shouldReturnSubjectForARefreshToken() {
    String refreshToken = provider.generateRefreshToken(user);

    assertThat(provider.validateRefreshTokenAndGetUserId(refreshToken))
        .isEqualTo(user.getId().toString());
  }

  @Test
  void validateRefreshTokenAndGetUserId_shouldRejectAnAccessToken() {
    String accessToken = provider.generateAccessToken(user);

    assertThatThrownBy(() -> provider.validateRefreshTokenAndGetUserId(accessToken))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Token is not a refresh token");
  }

  @Test
  void tokensSignedWithAnotherSecretAreRejected() {
    String foreignToken =
        new JwtTokenProvider(OTHER_SECRET, 3600, 2592000).generateAccessToken(user);

    assertThatThrownBy(() -> provider.validateAndGetClaims(foreignToken))
        .isInstanceOf(SignatureException.class);
    assertThat(provider.isTokenValid(foreignToken)).isFalse();
  }

  @Test
  void extractJti_shouldBeUniquePerRefreshToken() {
    String first = provider.extractJti(provider.generateRefreshToken(user));
    String second = provider.extractJti(provider.generateRefreshToken(user));

    assertThat(first).isNotBlank().isNotEqualTo(second);
  }

  @Test
  void extractJti_shouldBeNullForAnAccessToken() {
    assertThat(provider.extractJti(provider.generateAccessToken(user))).isNull();
  }
}
