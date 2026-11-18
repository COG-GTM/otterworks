package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.*;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

class JwtAuthFilterTest {

  private static final String SECRET =
      "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac";

  private final JwtAuthFilter filter =
      new JwtAuthFilter(new JwtTokenProvider(SECRET, 3600, 2592000));

  @AfterEach
  void clear() {
    SecurityContextHolder.clearContext();
  }

  private Authentication run(String authHeader) throws Exception {
    MockHttpServletRequest req = new MockHttpServletRequest();
    if (authHeader != null) {
      req.addHeader("Authorization", authHeader);
    }
    MockFilterChain chain = new MockFilterChain();
    filter.doFilter(req, new MockHttpServletResponse(), chain);
    assertThat(chain.getRequest()).isNotNull();
    return SecurityContextHolder.getContext().getAuthentication();
  }

  private String token(String type, Object roles) {
    var builder =
        Jwts.builder()
            .subject("user-1")
            .claim("type", type)
            .expiration(new Date(System.currentTimeMillis() + 60_000))
            .signWith(Keys.hmacShaKeyFor(SECRET.getBytes(StandardCharsets.UTF_8)));
    if (roles != null) {
      builder.claim("roles", roles);
    }
    return builder.compact();
  }

  @Test
  void shouldAuthenticateAccessTokenWithRoles() throws Exception {
    Authentication auth = run("Bearer " + token("access", java.util.List.of("ADMIN")));

    assertThat(auth.getPrincipal()).isEqualTo("user-1");
    assertThat(auth.getAuthorities()).extracting(Object::toString).containsExactly("ROLE_ADMIN");
  }

  @Test
  void shouldAuthenticateWithNoAuthoritiesWhenRolesClaimMissing() throws Exception {
    Authentication auth = run("Bearer " + token("access", null));

    assertThat(auth.getPrincipal()).isEqualTo("user-1");
    assertThat(auth.getAuthorities()).isEmpty();
  }

  @Test
  void shouldNotAuthenticateRefreshToken() throws Exception {
    assertThat(run("Bearer " + token("refresh", null))).isNull();
  }

  @Test
  void shouldIgnoreInvalidToken() throws Exception {
    assertThat(run("Bearer not.a.jwt")).isNull();
  }

  @Test
  void shouldIgnoreNonBearerHeader() throws Exception {
    assertThat(run("Basic dXNlcjpwYXNz")).isNull();
  }

  @Test
  void shouldIgnoreMissingHeader() throws Exception {
    assertThat(run(null)).isNull();
  }
}
