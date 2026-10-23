package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.*;

import com.otterworks.auth.entity.User;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

class JwtAuthFilterTest {

  private JwtTokenProvider provider;
  private JwtAuthFilter filter;
  private User user;

  @BeforeEach
  void setUp() {
    provider =
        new JwtTokenProvider(
            "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac", 3600, 60);
    filter = new JwtAuthFilter(provider);
    user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("filter@otterworks.dev");
    user.setDisplayName("Filter");
    user.setRoles(Set.of(User.Role.USER, User.Role.ADMIN));
    SecurityContextHolder.clearContext();
  }

  @AfterEach
  void tearDown() {
    SecurityContextHolder.clearContext();
  }

  private Authentication run(String authorizationHeader) throws Exception {
    MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/v1/auth/profile");
    if (authorizationHeader != null) {
      request.addHeader("Authorization", authorizationHeader);
    }
    MockFilterChain chain = new MockFilterChain();
    filter.doFilter(request, new MockHttpServletResponse(), chain);
    assertThat(chain.getRequest()).as("filter must always continue the chain").isNotNull();
    return SecurityContextHolder.getContext().getAuthentication();
  }

  @Test
  void validAccessTokenAuthenticatesWithRoleAuthorities() throws Exception {
    Authentication auth = run("Bearer " + provider.generateAccessToken(user));

    assertThat(auth).isNotNull();
    assertThat(auth.getPrincipal()).isEqualTo(user.getId().toString());
    assertThat(auth.getAuthorities())
        .extracting(GrantedAuthority::getAuthority)
        .containsExactlyInAnyOrder("ROLE_USER", "ROLE_ADMIN");
  }

  @Test
  void missingHeaderLeavesRequestAnonymous() throws Exception {
    assertThat(run(null)).isNull();
  }

  @Test
  void nonBearerSchemeIgnored() throws Exception {
    assertThat(run("Basic " + provider.generateAccessToken(user))).isNull();
  }

  @Test
  void refreshTokenDoesNotAuthenticate() throws Exception {
    assertThat(run("Bearer " + provider.generateRefreshToken(user))).isNull();
  }

  @Test
  void invalidTokenDoesNotAuthenticate() throws Exception {
    assertThat(run("Bearer garbage.token.value")).isNull();
  }

  @Test
  void expiredTokenDoesNotAuthenticate() throws Exception {
    JwtTokenProvider expired =
        new JwtTokenProvider(
            "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac", -5, -5);

    assertThat(run("Bearer " + expired.generateAccessToken(user))).isNull();
  }
}
