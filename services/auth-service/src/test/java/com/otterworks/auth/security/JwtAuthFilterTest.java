package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;

import com.otterworks.auth.entity.User;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import jakarta.servlet.FilterChain;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.Mockito;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

class JwtAuthFilterTest {

  private static final String SECRET =
      "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac";

  private JwtTokenProvider tokenProvider;
  private JwtAuthFilter filter;
  private MockHttpServletRequest request;
  private MockHttpServletResponse response;

  @BeforeEach
  void setUp() {
    tokenProvider =
        new JwtTokenProvider(
            SECRET, 3600,
            2592000); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
    filter = new JwtAuthFilter(tokenProvider);
    request = new MockHttpServletRequest();
    response = new MockHttpServletResponse();
    SecurityContextHolder.clearContext();
  }

  @AfterEach
  void tearDown() {
    SecurityContextHolder.clearContext();
  }

  @Test
  void shouldAuthenticateAccessTokenWithRoles() throws Exception {
    User user = user(Set.of(User.Role.USER, User.Role.ADMIN));
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateAccessToken(user));
    MockFilterChain chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    assertThat(authentication).isNotNull();
    assertThat(authentication.getPrincipal()).isEqualTo(user.getId().toString());
    assertThat(authentication.getAuthorities())
        .extracting(Object::toString)
        .containsExactlyInAnyOrder("ROLE_USER", "ROLE_ADMIN");
    assertThat(authentication.getDetails()).isNotNull();
    assertThat(chain.getRequest()).isSameAs(request);
  }

  @Test
  void shouldAuthenticateWithoutAuthoritiesWhenRolesClaimIsAbsent() throws Exception {
    User user = user(Set.of());
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateAccessToken(user));
    MockFilterChain chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    assertThat(authentication).isNotNull();
    assertThat(authentication.getAuthorities()).isEmpty();
  }

  @Test
  void shouldAuthenticateWithoutAuthoritiesWhenRolesClaimIsMissing() throws Exception {
    Instant now = Instant.now();
    String tokenWithoutRoles =
        Jwts.builder()
            .subject("33333333-3333-3333-3333-333333333333")
            .claim("type", "access")
            .issuedAt(Date.from(now))
            .expiration(Date.from(now.plusSeconds(3600)))
            .signWith(Keys.hmacShaKeyFor(SECRET.getBytes(StandardCharsets.UTF_8)))
            .compact();
    request.addHeader("Authorization", "Bearer " + tokenWithoutRoles);
    MockFilterChain chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    assertThat(authentication).isNotNull();
    assertThat(authentication.getPrincipal()).isEqualTo("33333333-3333-3333-3333-333333333333");
    assertThat(authentication.getAuthorities()).isEmpty();
  }

  @Test
  void shouldNotAuthenticateRefreshTokens() throws Exception {
    User user = user(Set.of(User.Role.USER));
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateRefreshToken(user));
    FilterChain chain = Mockito.mock(FilterChain.class);

    filter.doFilter(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    verify(chain).doFilter(request, response);
    Mockito.verifyNoMoreInteractions(chain);
  }

  @Test
  void shouldIgnoreTokenSignedWithAnotherKey() throws Exception {
    JwtTokenProvider foreignProvider =
        new JwtTokenProvider(
            "another-secret-that-is-also-long-enough-for-hmac-sha-256-ok",
            3600,
            2592000); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
    request.addHeader(
        "Authorization", "Bearer " + foreignProvider.generateAccessToken(user(Set.of())));
    MockFilterChain chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    assertThat(chain.getRequest()).isSameAs(request);
  }

  @Test
  void shouldIgnoreExpiredToken() throws Exception {
    JwtTokenProvider expiredProvider =
        new JwtTokenProvider(
            SECRET, -60,
            -60); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
    request.addHeader(
        "Authorization", "Bearer " + expiredProvider.generateAccessToken(user(Set.of())));
    MockFilterChain chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
  }

  @ParameterizedTest
  @ValueSource(strings = {"", "Bearer", "bearer token", "Basic dXNlcjpwYXNz", "Token abc"})
  void shouldSkipHeadersThatAreNotBearerTokens(String header) throws Exception {
    request.addHeader("Authorization", header);
    MockFilterChain chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    assertThat(chain.getRequest()).isSameAs(request);
  }

  @Test
  void shouldSkipRequestWithoutAuthorizationHeader() throws Exception {
    MockFilterChain chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    assertThat(chain.getRequest()).isSameAs(request);
  }

  @Test
  void shouldIgnoreMalformedBearerToken() throws Exception {
    request.addHeader("Authorization", "Bearer not-a-jwt");
    MockFilterChain chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
  }

  private User user(Set<User.Role> roles) {
    User user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("filter@otterworks.dev");
    user.setDisplayName("Filter User");
    user.setRoles(roles);
    return user;
  }
}
