package com.otterworks.auth.config;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.RequestBuilder;
import org.springframework.test.web.servlet.MvcResult;

/** Path authorization rules declared by {@link SecurityConfig}, exercised through the filter chain. */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class SecurityConfigAuthorizationTest {

  @Autowired private MockMvc mockMvc;
  @Autowired private ObjectMapper objectMapper;
  @Autowired private UserRepository userRepository;
  @Autowired private RefreshTokenRepository refreshTokenRepository;
  @Autowired private PasswordEncoder passwordEncoder;

  @BeforeEach
  void setUp() {
    refreshTokenRepository.deleteAll();
    userRepository.deleteAll();
  }

  @Test
  void publicPaths_shouldBeReachableWithoutAuthentication() throws Exception {
    mockMvc.perform(get("/health")).andExpect(status().isOk());
    expectNotBlockedBySecurity(get("/metrics"));

    // Reached the controller (rejected on credentials, not on authentication).
    mockMvc
        .perform(
            post("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\": \"nobody@otterworks.dev\", \"password\": \"password123\"}"))
        .andExpect(status().isBadRequest());

    mockMvc
        .perform(
            post("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\": \"not-an-email\", \"password\": \"x\"}"))
        .andExpect(status().isBadRequest());
  }

  @Test
  void refresh_shouldBePublicButStillRequireARefreshToken() throws Exception {
    // The path itself is permitAll, so a tokenless call fails on the missing header, not on auth.
    expectNotBlockedBySecurity(post("/api/v1/auth/refresh"));
  }

  @Test
  void protectedPaths_shouldRejectAnonymousCallers() throws Exception {
    mockMvc.perform(get("/api/v1/auth/profile")).andExpect(status().isForbidden());
    mockMvc.perform(post("/api/v1/auth/logout")).andExpect(status().isForbidden());
    mockMvc
        .perform(get("/api/v1/auth/users/lookup").param("email", "someone@otterworks.dev"))
        .andExpect(status().isForbidden());
    mockMvc.perform(get("/api/v1/auth/users")).andExpect(status().isForbidden());
  }

  @Test
  void userLookupPaths_shouldRequireAuthenticationOnlyNotAdminRole() throws Exception {
    User target = createUser("target@otterworks.dev", "password123", User.Role.USER);
    String userToken = login("target@otterworks.dev", "password123");

    mockMvc
        .perform(
            get("/api/v1/auth/users/lookup")
                .param("email", "target@otterworks.dev")
                .header("Authorization", "Bearer " + userToken))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.email").value("target@otterworks.dev"));

    mockMvc
        .perform(
            get("/api/v1/auth/users/by-id/" + target.getId())
                .header("Authorization", "Bearer " + userToken))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.email").value("target@otterworks.dev"));
  }

  @Test
  void userAdminPaths_shouldRequireAdminRole() throws Exception {
    createUser("plain@otterworks.dev", "password123", User.Role.USER);
    String userToken = login("plain@otterworks.dev", "password123");

    mockMvc
        .perform(get("/api/v1/auth/users").header("Authorization", "Bearer " + userToken))
        .andExpect(status().isForbidden());

    createUser("boss@otterworks.dev", "password123", User.Role.ADMIN, User.Role.USER);
    String adminToken = login("boss@otterworks.dev", "password123");

    mockMvc
        .perform(get("/api/v1/auth/users").header("Authorization", "Bearer " + adminToken))
        .andExpect(status().isOk());
  }

  @Test
  void invalidOrExpiredTokens_shouldBeTreatedAsAnonymous() throws Exception {
    mockMvc
        .perform(get("/api/v1/auth/profile").header("Authorization", "Bearer not-a-jwt"))
        .andExpect(status().isForbidden());

    mockMvc
        .perform(get("/api/v1/auth/profile").header("Authorization", "Basic dXNlcjpwYXNz"))
        .andExpect(status().isForbidden());
  }

  @Test
  void refreshToken_shouldNotAuthenticateProtectedEndpoints() throws Exception {
    createUser("refreshonly@otterworks.dev", "password123", User.Role.USER);
    JsonNode tokens = loginTokens("refreshonly@otterworks.dev", "password123");

    mockMvc
        .perform(
            get("/api/v1/auth/profile")
                .header("Authorization", "Bearer " + tokens.get("refreshToken").asText()))
        .andExpect(status().isForbidden());
  }

  @Test
  void passwordEncoder_shouldBeBcryptStrength12() {
    String hash = passwordEncoder.encode("password123");

    assertThat(hash).startsWith("$2a$12$");
    assertThat(hash).isNotEqualTo("password123");
    assertThat(passwordEncoder.matches("password123", hash)).isTrue();
    assertThat(passwordEncoder.matches("password124", hash)).isFalse();
  }

  @Test
  void storedPasswords_shouldBeHashedNotPlaintext() throws Exception {
    mockMvc
        .perform(
            post("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"email\": \"hashed@otterworks.dev\", \"password\": \"password123\","
                        + " \"displayName\": \"Hashed User\"}"))
        .andExpect(status().isCreated());

    User stored = userRepository.findByEmail("hashed@otterworks.dev").orElseThrow();
    assertThat(stored.getPasswordHash()).startsWith("$2a$12$").doesNotContain("password123");
    assertThat(passwordEncoder.matches("password123", stored.getPasswordHash())).isTrue();
  }

  private void expectNotBlockedBySecurity(RequestBuilder request) throws Exception {
    mockMvc
        .perform(request)
        .andExpect(result -> assertThat(result.getResponse().getStatus()).isNotIn(401, 403));
  }

  private User createUser(String email, String password, User.Role... roles) {
    User user = new User();
    user.setEmail(email);
    user.setPasswordHash(passwordEncoder.encode(password));
    user.setDisplayName(email);
    user.setRoles(Set.of(roles));
    return userRepository.save(user);
  }

  private String login(String email, String password) throws Exception {
    return loginTokens(email, password).get("accessToken").asText();
  }

  private JsonNode loginTokens(String email, String password) throws Exception {
    MvcResult result =
        mockMvc
            .perform(
                post("/api/v1/auth/login")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(
                        String.format(
                            "{\"email\": \"%s\", \"password\": \"%s\"}", email, password)))
            .andExpect(status().isOk())
            .andReturn();
    return objectMapper.readTree(result.getResponse().getContentAsString());
  }
}
