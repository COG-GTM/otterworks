package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.*;

import com.otterworks.auth.entity.User;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.security.WeakKeyException;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class JwtTokenProviderEdgeCaseTest {

  private static final String SECRET =
      "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac";

  private JwtTokenProvider provider;
  private User user;

  @BeforeEach
  void setUp() {
    provider = new JwtTokenProvider(SECRET, 3600, 2592000);
    user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("edge@otterworks.dev");
    user.setDisplayName("Edge");
    user.setRoles(Set.of(User.Role.ADMIN));
  }

  @Test
  void refreshTokenCannotBeUsedAsAccessToken() {
    String refresh = provider.generateRefreshToken(user);

    assertThatThrownBy(() -> provider.validateTokenAndGetUserId(refresh))
        .isInstanceOf(IllegalArgumentException.class);
  }

  @Test
  void accessTokenCannotBeUsedAsRefreshToken() {
    String access = provider.generateAccessToken(user);

    assertThatThrownBy(() -> provider.validateRefreshTokenAndGetUserId(access))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Token is not a refresh token");
  }

  @Test
  void validateRefreshToken_returnsSubject() {
    String refresh = provider.generateRefreshToken(user);

    assertThat(provider.validateRefreshTokenAndGetUserId(refresh))
        .isEqualTo(user.getId().toString());
  }

  @Test
  void accessTokenHasNoJti() {
    assertThat(provider.extractJti(provider.generateAccessToken(user))).isNull();
  }

  @Test
  void refreshTokensHaveUniqueJti() {
    String a = provider.extractJti(provider.generateRefreshToken(user));
    String b = provider.extractJti(provider.generateRefreshToken(user));

    assertThat(a).isNotBlank().isNotEqualTo(b);
  }

  @Test
  void tokenLifetimesMatchConfiguration() {
    Claims access = provider.validateAndGetClaims(provider.generateAccessToken(user));
    Claims refresh = provider.validateAndGetClaims(provider.generateRefreshToken(user));

    long accessTtl = (access.getExpiration().getTime() - access.getIssuedAt().getTime()) / 1000;
    long refreshTtl = (refresh.getExpiration().getTime() - refresh.getIssuedAt().getTime()) / 1000;
    assertThat(accessTtl).isEqualTo(3600);
    assertThat(refreshTtl).isEqualTo(2592000);
  }

  @Test
  void tokenSignedWithDifferentSecretRejected() {
    JwtTokenProvider other =
        new JwtTokenProvider("another-secret-that-is-also-at-least-32-bytes-long!!", 3600, 60);
    String foreign = other.generateAccessToken(user);

    assertThat(provider.isTokenValid(foreign)).isFalse();
    assertThatThrownBy(() -> provider.validateAndGetClaims(foreign))
        .isInstanceOf(JwtException.class);
  }

  @Test
  void tamperedPayloadRejected() {
    String token = provider.generateAccessToken(user);
    String[] parts = token.split("\\.");
    String forgedPayload =
        java.util.Base64.getUrlEncoder()
            .withoutPadding()
            .encodeToString(
                ("{\"sub\":\"" + UUID.randomUUID() + "\",\"roles\":[\"OWNER\"]}").getBytes());
    String forged = parts[0] + "." + forgedPayload + "." + parts[2];

    assertThat(provider.isTokenValid(forged)).isFalse();
  }

  @Test
  void unsignedTokenRejected() {
    String unsigned =
        io.jsonwebtoken.Jwts.builder()
            .subject(user.getId().toString())
            .claim("type", "access")
            .compact();

    assertThat(provider.isTokenValid(unsigned)).isFalse();
  }

  @Test
  void expiredAccessTokenThrowsExpiredJwtException() {
    JwtTokenProvider shortLived = new JwtTokenProvider(SECRET, -10, -10);
    String expired = shortLived.generateAccessToken(user);

    assertThatThrownBy(() -> provider.validateTokenAndGetUserId(expired))
        .isInstanceOf(ExpiredJwtException.class);
  }

  @Test
  void blankAndGarbageTokensAreInvalid() {
    assertThat(provider.isTokenValid("")).isFalse();
    assertThat(provider.isTokenValid("not.a.jwt")).isFalse();
  }

  @Test
  void secretShorterThan256BitsIsRejectedAtStartup() {
    assertThatThrownBy(() -> new JwtTokenProvider("too-short", 3600, 60))
        .isInstanceOf(WeakKeyException.class);
  }
}
