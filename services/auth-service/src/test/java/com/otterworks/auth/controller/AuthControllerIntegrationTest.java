package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import java.util.Map;
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
import org.springframework.test.web.servlet.MvcResult;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class AuthControllerIntegrationTest {

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
  void register_shouldCreateUserWithoutIssuingTokens() throws Exception {
    String body =
        """
        {"email": "newuser@otterworks.dev", "password": "password123", "displayName": "New User"}
        """;

    mockMvc
        .perform(
            post("/api/v1/auth/register").contentType(MediaType.APPLICATION_JSON).content(body))
        .andExpect(status().isAccepted())
        .andExpect(jsonPath("$.message").value(AuthController.REGISTER_ACCEPTED))
        .andExpect(jsonPath("$.accessToken").doesNotExist())
        .andExpect(jsonPath("$.user").doesNotExist());

    assertThat(userRepository.existsByEmail("newuser@otterworks.dev")).isTrue();
    loginAndGetAccessToken("newuser@otterworks.dev", "password123");
  }

  @Test
  void register_shouldNotRevealWhetherEmailIsRegistered() throws Exception {
    createTestUser("duplicate@otterworks.dev", "password123", "Duplicate User");

    MvcResult fresh =
        mockMvc
            .perform(
                post("/api/v1/auth/register")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(
                        """
                        {"email": "fresh@otterworks.dev", "password": "attacker-pw1", "displayName": "Probe"}
                        """))
            .andReturn();
    MvcResult existing =
        mockMvc
            .perform(
                post("/api/v1/auth/register")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(
                        """
                        {"email": "duplicate@otterworks.dev", "password": "attacker-pw1", "displayName": "Probe"}
                        """))
            .andReturn();

    assertThat(existing.getResponse().getStatus())
        .isEqualTo(fresh.getResponse().getStatus())
        .isEqualTo(202);
    assertThat(existing.getResponse().getContentAsString())
        .isEqualTo(fresh.getResponse().getContentAsString());

    User owner = userRepository.findByEmail("duplicate@otterworks.dev").orElseThrow();
    assertThat(owner.getDisplayName()).isEqualTo("Duplicate User");
    assertThat(passwordEncoder.matches("password123", owner.getPasswordHash())).isTrue();
    assertThat(passwordEncoder.matches("attacker-pw1", owner.getPasswordHash())).isFalse();
  }

  @Test
  void register_shouldRejectEmailLongerThanColumn() throws Exception {
    String email = "a".repeat(64) + "@" + ("b".repeat(60) + ".").repeat(4) + "com";
    String body =
        objectMapper.writeValueAsString(
            Map.of("email", email, "password", "password123", "displayName", "Long Email"));

    mockMvc
        .perform(
            post("/api/v1/auth/register").contentType(MediaType.APPLICATION_JSON).content(body))
        .andExpect(status().isBadRequest());
  }

  @Test
  void register_shouldRejectInvalidEmail() throws Exception {
    String body =
        """
        {"email": "not-an-email", "password": "password123", "displayName": "Bad Email"}
        """;

    mockMvc
        .perform(
            post("/api/v1/auth/register").contentType(MediaType.APPLICATION_JSON).content(body))
        .andExpect(status().isBadRequest());
  }

  @Test
  void login_shouldReturnTokensForValidCredentials() throws Exception {
    createTestUser("login@otterworks.dev", "password123", "Login User");

    String body =
        """
        {"email": "login@otterworks.dev", "password": "password123"}
        """;

    mockMvc
        .perform(post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON).content(body))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.accessToken").isNotEmpty())
        .andExpect(jsonPath("$.refreshToken").isNotEmpty())
        .andExpect(jsonPath("$.user.email").value("login@otterworks.dev"));
  }

  @Test
  void login_shouldRejectInvalidCredentials() throws Exception {
    createTestUser("login@otterworks.dev", "password123", "Login User");

    String body =
        """
        {"email": "login@otterworks.dev", "password": "wrongpassword"}
        """;

    mockMvc
        .perform(post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON).content(body))
        .andExpect(status().isBadRequest());
  }

  @Test
  void profile_shouldReturnUserProfile() throws Exception {
    String accessToken =
        registerAndGetAccessToken("profile@otterworks.dev", "password123", "Profile User");

    mockMvc
        .perform(get("/api/v1/auth/profile").header("Authorization", "Bearer " + accessToken))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.email").value("profile@otterworks.dev"))
        .andExpect(jsonPath("$.displayName").value("Profile User"));
  }

  @Test
  void profile_shouldRejectUnauthenticatedRequest() throws Exception {
    mockMvc.perform(get("/api/v1/auth/profile")).andExpect(status().isForbidden());
  }

  @Test
  void updateProfile_shouldUpdateDisplayName() throws Exception {
    String accessToken =
        registerAndGetAccessToken("update@otterworks.dev", "password123", "Original Name");

    String body = """
        {"displayName": "Updated Name"}
        """;

    mockMvc
        .perform(
            put("/api/v1/auth/profile")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content(body))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.displayName").value("Updated Name"));
  }

  @Test
  void changePassword_shouldSucceedWithCorrectOldPassword() throws Exception {
    String accessToken =
        registerAndGetAccessToken("changepw@otterworks.dev", "password123", "PW User");

    String body =
        """
        {"currentPassword": "password123", "newPassword": "newpassword456"}
        """;

    mockMvc
        .perform(
            post("/api/v1/auth/change-password")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content(body))
        .andExpect(status().isNoContent());

    // Verify new password works
    String loginBody =
        """
        {"email": "changepw@otterworks.dev", "password": "newpassword456"}
        """;
    mockMvc
        .perform(
            post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON).content(loginBody))
        .andExpect(status().isOk());
  }

  @Test
  void health_shouldReturnHealthStatus() throws Exception {
    mockMvc
        .perform(get("/health"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("healthy"))
        .andExpect(jsonPath("$.service").value("auth-service"))
        .andExpect(jsonPath("$.database.status").value("up"));
  }

  @Test
  void refresh_shouldReturnNewTokens() throws Exception {
    String registerBody =
        """
        {"email": "refresh@otterworks.dev", "password": "password123", "displayName": "Refresh User"}
        """;
    mockMvc
        .perform(
            post("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content(registerBody))
        .andExpect(status().isAccepted());

    String refreshToken =
        login("refresh@otterworks.dev", "password123").get("refreshToken").asText();

    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", "Bearer " + refreshToken))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.accessToken").isNotEmpty())
        .andExpect(jsonPath("$.refreshToken").isNotEmpty());
  }

  @Test
  void users_shouldRequireAdminRole() throws Exception {
    String accessToken =
        registerAndGetAccessToken("regular@otterworks.dev", "password123", "Regular User");

    mockMvc
        .perform(get("/api/v1/auth/users").header("Authorization", "Bearer " + accessToken))
        .andExpect(status().isForbidden());
  }

  @Test
  void users_shouldReturnPaginatedListForAdmin() throws Exception {
    User admin = new User();
    admin.setEmail("admin-test@otterworks.dev");
    admin.setPasswordHash(passwordEncoder.encode("admin123"));
    admin.setDisplayName("Admin Test");
    admin.setRoles(Set.of(User.Role.ADMIN, User.Role.USER));
    userRepository.save(admin);

    String loginBody =
        """
        {"email": "admin-test@otterworks.dev", "password": "admin123"}
        """;
    MvcResult loginResult =
        mockMvc
            .perform(
                post("/api/v1/auth/login")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(loginBody))
            .andExpect(status().isOk())
            .andReturn();

    JsonNode loginJson = objectMapper.readTree(loginResult.getResponse().getContentAsString());
    String adminToken = loginJson.get("accessToken").asText();

    mockMvc
        .perform(
            get("/api/v1/auth/users")
                .header("Authorization", "Bearer " + adminToken)
                .param("page", "0")
                .param("size", "10"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.content").isArray());
  }

  private void createTestUser(String email, String password, String displayName) {
    User user = new User();
    user.setEmail(email);
    user.setPasswordHash(passwordEncoder.encode(password));
    user.setDisplayName(displayName);
    user.setRoles(Set.of(User.Role.USER));
    userRepository.save(user);
  }

  private String registerAndGetAccessToken(String email, String password, String displayName)
      throws Exception {
    String body =
        String.format(
            "{\"email\": \"%s\", \"password\": \"%s\", \"displayName\": \"%s\"}",
            email, password, displayName);

    mockMvc
        .perform(
            post("/api/v1/auth/register").contentType(MediaType.APPLICATION_JSON).content(body))
        .andExpect(status().isAccepted());

    return loginAndGetAccessToken(email, password);
  }

  private String loginAndGetAccessToken(String email, String password) throws Exception {
    return login(email, password).get("accessToken").asText();
  }

  private JsonNode login(String email, String password) throws Exception {
    String body = String.format("{\"email\": \"%s\", \"password\": \"%s\"}", email, password);

    MvcResult result =
        mockMvc
            .perform(
                post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON).content(body))
            .andExpect(status().isOk())
            .andReturn();

    return objectMapper.readTree(result.getResponse().getContentAsString());
  }
}
