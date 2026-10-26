package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.*;

import com.otterworks.auth.entity.User;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class JwtTokenProviderTest {

  private JwtTokenProvider jwtTokenProvider;

  @BeforeEach
  void setUp() {
    jwtTokenProvider =
        new JwtTokenProvider(
            "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac",
            3600,
            2592000); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
  }

  @Test
  void constructor_shouldRejectMissingSecret() {
    assertThatThrownBy(() -> new JwtTokenProvider(null, 3600, 2592000))
        .isInstanceOf(IllegalStateException.class)
        .hasMessageContaining("JWT_SECRET");
    assertThatThrownBy(() -> new JwtTokenProvider("", 3600, 2592000))
        .isInstanceOf(IllegalStateException.class)
        .hasMessageContaining("JWT_SECRET");
    assertThatThrownBy(() -> new JwtTokenProvider("   ", 3600, 2592000))
        .isInstanceOf(IllegalStateException.class)
        .hasMessageContaining("JWT_SECRET");
  }

  @Test
  void constructor_shouldRejectSecretsPublishedInTheRepository() {
    for (String published : JwtTokenProvider.PUBLISHED_SECRETS) {
      assertThatThrownBy(() -> new JwtTokenProvider(published, 3600, 2592000))
          .isInstanceOf(IllegalStateException.class)
          .hasMessageContaining("published");
    }
  }

  @Test
  void constructor_shouldRejectSecretsShorterThan32Bytes() {
    assertThatThrownBy(() -> new JwtTokenProvider("a".repeat(31), 3600, 2592000))
        .isInstanceOf(IllegalStateException.class)
        .hasMessageContaining("at least 32 bytes");
    assertThatCode(() -> new JwtTokenProvider("a".repeat(32), 3600, 2592000))
        .doesNotThrowAnyException();
  }

  @Test
  void validateAndGetClaims_shouldRejectTokenSignedWithPublishedDefault() {
    String forged =
        Jwts.builder()
            .subject(UUID.randomUUID().toString())
            .claim("roles", List.of("ADMIN"))
            .claim("type", "access")
            .expiration(new Date(System.currentTimeMillis() + 3_600_000))
            .signWith(
                Keys.hmacShaKeyFor(
                    "dev-jwt-secret-otterworks-2024-change-in-production"
                        .getBytes(StandardCharsets.UTF_8)))
            .compact();

    assertThatThrownBy(() -> jwtTokenProvider.validateAndGetClaims(forged))
        .isInstanceOf(JwtException.class);
  }

  @Test
  void generateAccessToken_shouldContainUserClaims() {
    User user = createTestUser();

    String token = jwtTokenProvider.generateAccessToken(user);

    assertThat(token).isNotBlank();
    Claims claims = jwtTokenProvider.validateAndGetClaims(token);
    assertThat(claims.getSubject()).isEqualTo(user.getId().toString());
    assertThat(claims.get("email", String.class)).isEqualTo("test@otterworks.dev");
    assertThat(claims.get("name", String.class)).isEqualTo("Test User");
    assertThat(claims.get("type", String.class)).isEqualTo("access");

    @SuppressWarnings("unchecked")
    List<String> roles = claims.get("roles", List.class);
    assertThat(roles).contains("USER");
  }

  @Test
  void generateRefreshToken_shouldContainJtiAndType() {
    User user = createTestUser();

    String token = jwtTokenProvider.generateRefreshToken(user);

    assertThat(token).isNotBlank();
    Claims claims = jwtTokenProvider.validateAndGetClaims(token);
    assertThat(claims.getSubject()).isEqualTo(user.getId().toString());
    assertThat(claims.get("type", String.class)).isEqualTo("refresh");
    assertThat(claims.getId()).isNotBlank();
  }

  @Test
  void validateTokenAndGetUserId_shouldReturnUserId() {
    User user = createTestUser();
    String token = jwtTokenProvider.generateAccessToken(user);

    String userId = jwtTokenProvider.validateTokenAndGetUserId(token);

    assertThat(userId).isEqualTo(user.getId().toString());
  }

  @Test
  void extractJti_shouldReturnJtiFromRefreshToken() {
    User user = createTestUser();
    String token = jwtTokenProvider.generateRefreshToken(user);

    String jti = jwtTokenProvider.extractJti(token);

    assertThat(jti).isNotBlank();
  }

  @Test
  void isTokenValid_shouldReturnTrueForValidToken() {
    User user = createTestUser();
    String token = jwtTokenProvider.generateAccessToken(user);

    assertThat(jwtTokenProvider.isTokenValid(token)).isTrue();
  }

  @Test
  void isTokenValid_shouldReturnFalseForInvalidToken() {
    assertThat(jwtTokenProvider.isTokenValid("invalid.token.here")).isFalse();
  }

  @Test
  void isTokenValid_shouldReturnFalseForExpiredToken() {
    JwtTokenProvider shortLivedProvider =
        new JwtTokenProvider(
            "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac",
            -1,
            -1); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
    User user = createTestUser();
    String token = shortLivedProvider.generateAccessToken(user);

    assertThat(shortLivedProvider.isTokenValid(token)).isFalse();
  }

  @Test
  void getAccessTokenExpiry_shouldReturnConfiguredValue() {
    assertThat(jwtTokenProvider.getAccessTokenExpiry()).isEqualTo(3600);
  }

  @Test
  void getRefreshTokenExpiry_shouldReturnConfiguredValue() {
    assertThat(jwtTokenProvider.getRefreshTokenExpiry()).isEqualTo(2592000);
  }

  private User createTestUser() {
    User user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("test@otterworks.dev");
    user.setDisplayName("Test User");
    user.setPasswordHash(
        "$2a$12$hashedpassword"); // nosemgrep: generic.secrets.security.detected-bcrypt-hash
    user.setRoles(Set.of(User.Role.USER));
    return user;
  }
}
