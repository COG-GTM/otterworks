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

  private static final String SECRET =
      "test-jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac";

  private JwtTokenProvider tokenProvider;
  private JwtAuthFilter filter;
  private User user;

  @BeforeEach
  void setUp() {
    tokenProvider = new JwtTokenProvider(SECRET, 3600, 2592000);
    filter = new JwtAuthFilter(tokenProvider);
    user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("filter@otterworks.dev");
    user.setDisplayName("Filter User");
    user.setRoles(Set.of(User.Role.USER, User.Role.ADMIN));
    SecurityContextHolder.clearContext();
  }

  @AfterEach
  void tearDown() {
    SecurityContextHolder.clearContext();
  }

  private Authentication runFilter(String authorizationHeader) throws Exception {
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
  void accessToken_shouldAuthenticateWithSubjectAndRoleAuthorities() throws Exception {
    Authentication auth = runFilter("Bearer " + tokenProvider.generateAccessToken(user));

    assertThat(auth).isNotNull();
    assertThat(auth.getPrincipal()).isEqualTo(user.getId().toString());
    assertThat(auth.getAuthorities())
        .extracting(GrantedAuthority::getAuthority)
        .containsExactlyInAnyOrder("ROLE_USER", "ROLE_ADMIN");
  }

  @Test
  void refreshToken_shouldNotAuthenticate() throws Exception {
    assertThat(runFilter("Bearer " + tokenProvider.generateRefreshToken(user))).isNull();
  }

  @Test
  void tokenSignedWithDifferentKey_shouldNotAuthenticate() throws Exception {
    JwtTokenProvider attacker =
        new JwtTokenProvider("attacker-controlled-secret-that-is-also-32-bytes-long", 3600, 60);

    assertThat(runFilter("Bearer " + attacker.generateAccessToken(user))).isNull();
  }

  @Test
  void tamperedToken_shouldNotAuthenticate() throws Exception {
    String token = tokenProvider.generateAccessToken(user);
    String[] parts = token.split("\\.");
    String forgedPayload =
        java.util.Base64.getUrlEncoder()
            .withoutPadding()
            .encodeToString(
                ("{\"sub\":\""
                        + UUID.randomUUID()
                        + "\",\"roles\":[\"ADMIN\"],\"type\":\"access\"}")
                    .getBytes(java.nio.charset.StandardCharsets.UTF_8));

    assertThat(runFilter("Bearer " + parts[0] + "." + forgedPayload + "." + parts[2])).isNull();
  }

  @Test
  void expiredAccessToken_shouldNotAuthenticate() throws Exception {
    JwtTokenProvider expired = new JwtTokenProvider(SECRET, -60, 60);

    assertThat(runFilter("Bearer " + expired.generateAccessToken(user))).isNull();
  }

  @Test
  void missingOrNonBearerHeader_shouldNotAuthenticate() throws Exception {
    assertThat(runFilter(null)).isNull();
    assertThat(runFilter("Basic dXNlcjpwYXNz")).isNull();
    assertThat(runFilter(tokenProvider.generateAccessToken(user))).isNull();
  }
}
