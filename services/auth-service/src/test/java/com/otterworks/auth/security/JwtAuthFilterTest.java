package com.otterworks.auth.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;

import com.otterworks.auth.entity.User;
import jakarta.servlet.FilterChain;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.Mockito;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetails;

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
    chain = Mockito.mock(FilterChain.class);
    SecurityContextHolder.clearContext();
  }

  @AfterEach
  void clearContext() {
    SecurityContextHolder.clearContext();
  }

  private static User user(Set<User.Role> roles) {
    User user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("user@otterworks.dev");
    user.setDisplayName("User One");
    user.setRoles(roles);
    return user;
  }

  private Authentication currentAuthentication() {
    return SecurityContextHolder.getContext().getAuthentication();
  }

  @Test
  void aValidAccessTokenAuthenticatesTheUserWithPrefixedRoles() throws Exception {
    User user = user(Set.of(User.Role.USER, User.Role.ADMIN));
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateAccessToken(user));

    filter.doFilter(request, response, chain);

    Authentication authentication = currentAuthentication();
    assertThat(authentication).isNotNull();
    assertThat(authentication.getPrincipal()).isEqualTo(user.getId().toString());
    assertThat(authentication.getCredentials()).isNull();
    assertThat(authentication.getAuthorities())
        .extracting(Object::toString)
        .containsExactlyInAnyOrder("ROLE_USER", "ROLE_ADMIN");
    assertThat(authentication.getDetails()).isInstanceOf(WebAuthenticationDetails.class);
    verify(chain).doFilter(request, response);
  }

  @Test
  void aUserWithNoRolesIsAuthenticatedWithNoAuthorities() throws Exception {
    User user = user(Set.of());
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateAccessToken(user));

    filter.doFilter(request, response, chain);

    assertThat(currentAuthentication()).isNotNull();
    assertThat(currentAuthentication().getAuthorities()).isEmpty();
    verify(chain).doFilter(request, response);
  }

  @Test
  void aRefreshTokenIsPassedThroughWithoutAuthenticating() throws Exception {
    User user = user(Set.of(User.Role.USER));
    request.addHeader("Authorization", "Bearer " + tokenProvider.generateRefreshToken(user));

    filter.doFilter(request, response, chain);

    assertThat(currentAuthentication()).isNull();
    verify(chain).doFilter(request, response);
  }

  @Test
  void aTokenWithoutARolesClaimAuthenticatesWithNoAuthorities() throws Exception {
    String tokenWithoutRoles =
        io.jsonwebtoken.Jwts.builder()
            .subject(UUID.randomUUID().toString())
            .claim("type", "access")
            .signWith(
                io.jsonwebtoken.security.Keys.hmacShaKeyFor(
                    SECRET.getBytes(java.nio.charset.StandardCharsets.UTF_8)))
            .compact();
    request.addHeader("Authorization", "Bearer " + tokenWithoutRoles);

    filter.doFilter(request, response, chain);

    assertThat(currentAuthentication()).isNotNull();
    assertThat(currentAuthentication().getAuthorities()).isEmpty();
  }

  @Test
  void aTokenSignedWithAnotherKeyLeavesTheRequestAnonymous() throws Exception {
    JwtTokenProvider foreignProvider =
        new JwtTokenProvider("a-completely-different-secret-that-is-long-enough-32", 3600, 2592000);
    request.addHeader(
        "Authorization", "Bearer " + foreignProvider.generateAccessToken(user(Set.of())));

    filter.doFilter(request, response, chain);

    assertThat(currentAuthentication()).isNull();
    verify(chain).doFilter(request, response);
  }

  @Test
  void anExpiredTokenLeavesTheRequestAnonymous() throws Exception {
    JwtTokenProvider expiredProvider = new JwtTokenProvider(SECRET, -60, -60);
    request.addHeader(
        "Authorization", "Bearer " + expiredProvider.generateAccessToken(user(Set.of())));

    filter.doFilter(request, response, chain);

    assertThat(currentAuthentication()).isNull();
    verify(chain).doFilter(request, response);
  }

  @ParameterizedTest(name = "Authorization: \"{0}\" is ignored")
  @ValueSource(strings = {"", "Basic dXNlcjpwYXNz", "bearer lowercase-prefix", "Bearer"})
  void anUnusableAuthorizationHeaderLeavesTheRequestAnonymous(String header) throws Exception {
    request.addHeader("Authorization", header);

    filter.doFilter(request, response, chain);

    assertThat(currentAuthentication()).isNull();
    verify(chain).doFilter(request, response);
  }

  @Test
  void aRequestWithNoAuthorizationHeaderIsPassedThrough() throws Exception {
    filter.doFilter(request, response, chain);

    assertThat(currentAuthentication()).isNull();
    verify(chain).doFilter(request, response);
  }

  @Test
  void garbageAfterTheBearerPrefixLeavesTheRequestAnonymous() throws Exception {
    request.addHeader("Authorization", "Bearer not.a.jwt");

    filter.doFilter(request, response, chain);

    assertThat(currentAuthentication()).isNull();
    verify(chain).doFilter(request, response);
  }
}
