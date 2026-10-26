package com.otterworks.auth.security;

import com.otterworks.auth.entity.User;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import javax.crypto.SecretKey;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class JwtTokenProvider {

  static final int MIN_SECRET_BYTES = 32;

  // Signing keys that were committed to this repository as defaults at some point.
  static final Set<String> PUBLISHED_SECRETS =
      Set.of(
          "dev-jwt-secret-otterworks-2024-change-in-production",
          "otterworks-local-dev-jwt-secret-change-me-in-production",
          "otterworks-dev-secret",
          "dev_jwt_secret_key");

  private final SecretKey key;
  private final long accessTokenExpiry;
  private final long refreshTokenExpiry;

  public JwtTokenProvider(
      @Value("${jwt.secret}") String secret,
      @Value("${jwt.access-token-expiry:3600}") long accessTokenExpiry,
      @Value("${jwt.refresh-token-expiry:2592000}") long refreshTokenExpiry) {
    this.key = Keys.hmacShaKeyFor(requireStrongSecret(secret));
    this.accessTokenExpiry = accessTokenExpiry;
    this.refreshTokenExpiry = refreshTokenExpiry;
  }

  static byte[] requireStrongSecret(String secret) {
    if (secret == null || secret.isBlank()) {
      throw new IllegalStateException("JWT_SECRET environment variable is required but not set");
    }
    if (PUBLISHED_SECRETS.contains(secret.trim())) {
      throw new IllegalStateException(
          "JWT_SECRET is set to a value published in the OtterWorks repository; generate a new"
              + " one (e.g. make env or openssl rand -hex 32)");
    }
    byte[] bytes = secret.getBytes(StandardCharsets.UTF_8);
    if (bytes.length < MIN_SECRET_BYTES) {
      throw new IllegalStateException(
          "JWT_SECRET must be at least " + MIN_SECRET_BYTES + " bytes long");
    }
    return bytes;
  }

  public String generateAccessToken(User user) {
    Instant now = Instant.now();
    return Jwts.builder()
        .subject(user.getId().toString())
        .claim("email", user.getEmail())
        .claim("name", user.getDisplayName())
        .claim("roles", user.getRoles().stream().map(Enum::name).collect(Collectors.toList()))
        .claim("type", "access")
        .issuedAt(Date.from(now))
        .expiration(Date.from(now.plus(accessTokenExpiry, ChronoUnit.SECONDS)))
        .signWith(key)
        .compact();
  }

  public String generateRefreshToken(User user) {
    String jti = UUID.randomUUID().toString();
    Instant now = Instant.now();
    return Jwts.builder()
        .subject(user.getId().toString())
        .id(jti)
        .claim("type", "refresh")
        .issuedAt(Date.from(now))
        .expiration(Date.from(now.plus(refreshTokenExpiry, ChronoUnit.SECONDS)))
        .signWith(key)
        .compact();
  }

  public Claims validateAndGetClaims(String token) {
    return Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload();
  }

  public String validateTokenAndGetUserId(String token) {
    Claims claims = validateAndGetClaims(token);
    String type = claims.get("type", String.class);
    if ("refresh".equals(type)) {
      throw new IllegalArgumentException("Refresh token cannot be used as access token");
    }
    return claims.getSubject();
  }

  public String validateRefreshTokenAndGetUserId(String token) {
    Claims claims = validateAndGetClaims(token);
    String type = claims.get("type", String.class);
    if (!"refresh".equals(type)) {
      throw new IllegalArgumentException("Token is not a refresh token");
    }
    return claims.getSubject();
  }

  public String extractJti(String token) {
    Claims claims = validateAndGetClaims(token);
    return claims.getId();
  }

  public boolean isTokenValid(String token) {
    try {
      validateAndGetClaims(token);
      return true;
    } catch (JwtException | IllegalArgumentException e) {
      return false;
    }
  }

  public long getAccessTokenExpiry() {
    return accessTokenExpiry;
  }

  public long getRefreshTokenExpiry() {
    return refreshTokenExpiry;
  }
}
