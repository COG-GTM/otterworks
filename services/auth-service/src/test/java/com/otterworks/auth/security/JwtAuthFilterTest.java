package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
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
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.preauth.PreAuthenticatedAuthenticationToken;

class JwtAuthFilterTest {

  private static final String SECRET =
      "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac";

  private JwtTokenProvider tokenProvider;
  private JwtAuthFilter filter;
  private MockHttpServletRequest request;
  private MockHttpServletResponse response;
  private FilterChain chain;

  @BeforeEach
  void setUp() {
    tokenProvider = new JwtTokenProvider(SECRET, 3600, 2592000);
    filter = new JwtAuthFilter(tokenProvider);
    request = new MockHttpServletRequest();
    response = new MockHttpServletResponse();
    chain = mock(FilterChain.class);
  }

  @AfterEach
  void clearContext() {
    SecurityContextHolder.clearContext();
  }

  @Test
  void accessTokenPopulatesAuthenticationWithPrefixedRoles() throws Exception {
    User user = user(Set.of(User.Role.USER, User.Role.ADMIN));
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateAccessToken(user));

    filter.doFilterInternal(request, response, chain);

    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    assertThat(authentication).isNotNull();
    assertThat(authentication.getPrincipal()).isEqualTo(user.getId().toString());
    assertThat(authentication.getAuthorities())
        .extracting(Object::toString)
        .containsExactlyInAnyOrder("ROLE_USER", "ROLE_ADMIN");
    assertThat(authentication.getDetails()).isNotNull();
    verify(chain).doFilter(request, response);
  }

  @Test
  void refreshTokenIsNotAcceptedAsAuthentication() throws Exception {
    User user = user(Set.of(User.Role.USER));
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateRefreshToken(user));

    filter.doFilterInternal(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    verify(chain).doFilter(request, response);
  }

  @Test
  void tokenWithEmptyRolesClaimYieldsNoAuthorities() throws Exception {
    User user = user(Set.of());
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateAccessToken(user));

    filter.doFilterInternal(request, response, chain);

    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    assertThat(authentication).isNotNull();
    assertThat(authentication.getAuthorities()).isEmpty();
  }

  @Test
  void tokenWithoutRolesClaimYieldsNoAuthorities() throws Exception {
    String token =
        Jwts.builder()
            .subject(UUID.randomUUID().toString())
            .claim("type", "access")
            .signWith(Keys.hmacShaKeyFor(SECRET.getBytes(StandardCharsets.UTF_8)))
            .compact();
    request.addHeader("Authorization", "Bearer " + token);

    filter.doFilterInternal(request, response, chain);

    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    assertThat(authentication).isNotNull();
    assertThat(authentication.getAuthorities()).isEmpty();
  }

  @Test
  void malformedTokenLeavesContextUnauthenticatedAndContinuesTheChain() throws Exception {
    request.addHeader("Authorization", "Bearer not-a-jwt");

    filter.doFilterInternal(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    verify(chain).doFilter(request, response);
  }

  @Test
  void missingHeaderSkipsAuthentication() throws Exception {
    filter.doFilterInternal(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    verify(chain).doFilter(request, response);
  }

  @Test
  void nonBearerHeaderSkipsAuthentication() throws Exception {
    request.addHeader("Authorization", "Basic dXNlcjpwYXNz");

    filter.doFilterInternal(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    verify(chain).doFilter(request, response);
  }

  @Test
  void existingAuthenticationIsReplacedByTheTokenIdentity() throws Exception {
    SecurityContextHolder.getContext()
        .setAuthentication(new PreAuthenticatedAuthenticationToken("someone-else", null));
    User user = user(Set.of(User.Role.USER));
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateAccessToken(user));

    filter.doFilterInternal(request, response, chain);

    assertThat(SecurityContextHolder.getContext().getAuthentication().getPrincipal())
        .isEqualTo(user.getId().toString());
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
