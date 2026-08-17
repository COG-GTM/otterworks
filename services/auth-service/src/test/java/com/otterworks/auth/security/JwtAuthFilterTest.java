package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;

import com.otterworks.auth.entity.User;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import jakarta.servlet.FilterChain;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

@ExtendWith(MockitoExtension.class)
class JwtAuthFilterTest {

  private static final String SECRET =
      "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac";

  @Mock private FilterChain filterChain;

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

  private User user(Set<User.Role> roles) {
    User user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("filter@otterworks.dev");
    user.setDisplayName("Filter User");
    user.setRoles(roles);
    return user;
  }

  @Test
  void accessTokenAuthenticatesWithPrefixedRoles() throws Exception {
    User user = user(Set.of(User.Role.ADMIN));
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateAccessToken(user));

    filter.doFilter(request, response, filterChain);

    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    assertThat(authentication.getPrincipal()).isEqualTo(user.getId().toString());
    assertThat(authentication.getAuthorities())
        .extracting(Object::toString)
        .containsExactly("ROLE_ADMIN");
    assertThat(authentication.getDetails()).isNotNull();
    verify(filterChain).doFilter(request, response);
  }

  @Test
  void tokenWithoutRolesAuthenticatesWithNoAuthorities() throws Exception {
    User user = user(Set.of());
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateAccessToken(user));

    filter.doFilter(request, response, filterChain);

    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    assertThat(authentication.getPrincipal()).isEqualTo(user.getId().toString());
    assertThat(authentication.getAuthorities()).isEmpty();
    verify(filterChain).doFilter(request, response);
  }

  @Test
  void tokenWithoutARolesClaimAuthenticatesWithNoAuthorities() throws Exception {
    String subject = UUID.randomUUID().toString();
    String token =
        Jwts.builder()
            .subject(subject)
            .claim("type", "access")
            .signWith(Keys.hmacShaKeyFor(SECRET.getBytes(StandardCharsets.UTF_8)))
            .compact();
    request.addHeader("Authorization", "Bearer " + token);

    filter.doFilter(request, response, filterChain);

    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    assertThat(authentication.getPrincipal()).isEqualTo(subject);
    assertThat(authentication.getAuthorities()).isEmpty();
    verify(filterChain).doFilter(request, response);
  }

  @Test
  void refreshTokenIsNotAcceptedAsAnAccessToken() throws Exception {
    User user = user(Set.of(User.Role.USER));
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateRefreshToken(user));

    filter.doFilter(request, response, filterChain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    verify(filterChain).doFilter(request, response);
  }

  @Test
  void requestWithoutAuthorizationHeaderStaysAnonymous() throws Exception {
    filter.doFilter(request, response, filterChain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    verify(filterChain).doFilter(request, response);
  }

  @Test
  void nonBearerAuthorizationHeaderIsIgnored() throws Exception {
    request.addHeader("Authorization", "Basic dXNlcjpwYXNz");

    filter.doFilter(request, response, filterChain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    verify(filterChain).doFilter(request, response);
  }

  @Test
  void malformedTokenLeavesTheRequestUnauthenticatedAndStillChains() throws Exception {
    request.addHeader("Authorization", "Bearer not-a-jwt");

    filter.doFilter(request, response, filterChain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    verify(filterChain).doFilter(request, response);
  }

  @Test
  void tokenSignedWithAnotherKeyIsRejected() throws Exception {
    JwtTokenProvider foreignProvider =
        new JwtTokenProvider(
            "another-jwt-secret-otterworks-that-is-also-at-least-32-bytes",
            3600,
            2592000); // nosemgrep: java.lang.security.audit.crypto.no-static-initialization-vector
    request.addHeader(
        "Authorization", "Bearer " + foreignProvider.generateAccessToken(user(Set.of())));

    filter.doFilter(request, response, filterChain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    verify(filterChain).doFilter(request, response);
  }
}
