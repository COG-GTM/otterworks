package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.*;

import com.otterworks.auth.entity.User;
import io.jsonwebtoken.Claims;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class JwtTokenProviderTest {

  private static final String SECRET =
      "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac";
  private static final String ISSUER = "otterworks-auth-service";
  private static final String AUDIENCE = "otterworks-tenant-a";

  private JwtTokenProvider jwtTokenProvider;

  @BeforeEach
  void setUp() {
    jwtTokenProvider =
        new JwtTokenProvider(
            SECRET,
            3600,
            2592000,
            ISSUER,
            AUDIENCE); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
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
            SECRET,
            -1,
            -1,
            ISSUER,
            AUDIENCE); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
    User user = createTestUser();
    String token = shortLivedProvider.generateAccessToken(user);

    assertThat(shortLivedProvider.isTokenValid(token)).isFalse();
  }

  @Test
  void generatedTokens_shouldCarryIssuerAndTenantAudience() {
    User user = createTestUser();

    Claims access = jwtTokenProvider.validateAndGetClaims(jwtTokenProvider.generateAccessToken(user));
    Claims refresh =
        jwtTokenProvider.validateAndGetClaims(jwtTokenProvider.generateRefreshToken(user));

    assertThat(access.getIssuer()).isEqualTo(ISSUER);
    assertThat(access.getAudience()).containsExactly(AUDIENCE);
    assertThat(refresh.getIssuer()).isEqualTo(ISSUER);
    assertThat(refresh.getAudience()).containsExactly(AUDIENCE);
  }

  @Test
  void tokenFromAnotherTenant_shouldBeRejectedEvenWithSameSecret() {
    JwtTokenProvider otherTenant =
        new JwtTokenProvider(SECRET, 3600, 2592000, ISSUER, "otterworks-tenant-b");
    User user = createTestUser();
    String foreignAccess = otherTenant.generateAccessToken(user);
    String foreignRefresh = otherTenant.generateRefreshToken(user);

    assertThat(jwtTokenProvider.isTokenValid(foreignAccess)).isFalse();
    assertThat(jwtTokenProvider.isTokenValid(foreignRefresh)).isFalse();
    assertThatThrownBy(() -> jwtTokenProvider.validateTokenAndGetUserId(foreignAccess))
        .isInstanceOf(io.jsonwebtoken.JwtException.class);
  }

  @Test
  void tokenWithoutIssuerOrAudience_shouldBeRejected() {
    String bare =
        io.jsonwebtoken.Jwts.builder()
            .subject(UUID.randomUUID().toString())
            .claim("roles", List.of("OWNER"))
            .signWith(
                io.jsonwebtoken.security.Keys.hmacShaKeyFor(
                    SECRET.getBytes(java.nio.charset.StandardCharsets.UTF_8)))
            .compact();

    assertThat(jwtTokenProvider.isTokenValid(bare)).isFalse();
  }

  @Test
  void blankAudience_shouldFailFast() {
    assertThatThrownBy(() -> new JwtTokenProvider(SECRET, 3600, 2592000, ISSUER, " "))
        .isInstanceOf(IllegalArgumentException.class);
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
