package com.otterworks.auth.controller;

import static com.github.tomakehurst.wiremock.client.WireMock.*;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.wireMockConfig;
import static org.assertj.core.api.Assertions.*;
import static org.awaitility.Awaitility.await;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.tomakehurst.wiremock.client.WireMock;
import com.github.tomakehurst.wiremock.junit5.WireMockExtension;
import com.github.tomakehurst.wiremock.stubbing.ServeEvent;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class AuthControllerIntegrationTest {

  private static final String AUDIT_PATH = "/api/v1/audit/events";
  private static final String CLIENT_IP = "203.0.113.7";

  @RegisterExtension
  static WireMockExtension auditService =
      WireMockExtension.newInstance().options(wireMockConfig().dynamicPort()).build();

  @DynamicPropertySource
  static void auditProperties(DynamicPropertyRegistry registry) {
    registry.add("audit.service-url", auditService::baseUrl);
  }

  @Autowired private MockMvc mockMvc;
  @Autowired private MeterRegistry meterRegistry;
  @Autowired private ObjectMapper objectMapper;
  @Autowired private UserRepository userRepository;
  @Autowired private RefreshTokenRepository refreshTokenRepository;
  @Autowired private PasswordEncoder passwordEncoder;

  @BeforeEach
  void setUp() {
    refreshTokenRepository.deleteAll();
    userRepository.deleteAll();
    auditService.stubFor(WireMock.post(AUDIT_PATH).willReturn(aResponse().withStatus(201)));
  }

  @Test
  void register_shouldCreateUserAndReturnTokens() throws Exception {
    String body =
        """
        {"email": "newuser@otterworks.dev", "password": "password123", "displayName": "New User"}
        """;

    MvcResult result =
        mockMvc
            .perform(
                post("/api/v1/auth/register").contentType(MediaType.APPLICATION_JSON).content(body))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.accessToken").isNotEmpty())
            .andExpect(jsonPath("$.refreshToken").isNotEmpty())
            .andExpect(jsonPath("$.tokenType").value("Bearer"))
            .andExpect(jsonPath("$.user.email").value("newuser@otterworks.dev"))
            .andReturn();

    assertThat(userRepository.existsByEmail("newuser@otterworks.dev")).isTrue();
  }

  @Test
  void register_shouldRejectDuplicateEmail() throws Exception {
    createTestUser("duplicate@otterworks.dev", "password123", "Duplicate User");

    String body =
        """
        {"email": "duplicate@otterworks.dev", "password": "password123", "displayName": "Dup User"}
        """;

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
    MvcResult registerResult =
        mockMvc
            .perform(
                post("/api/v1/auth/register")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(registerBody))
            .andExpect(status().isCreated())
            .andReturn();

    JsonNode registerJson =
        objectMapper.readTree(registerResult.getResponse().getContentAsString());
    String refreshToken = registerJson.get("refreshToken").asText();

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

    MvcResult result =
        mockMvc
            .perform(
                post("/api/v1/auth/register").contentType(MediaType.APPLICATION_JSON).content(body))
            .andExpect(status().isCreated())
            .andReturn();

    JsonNode json = objectMapper.readTree(result.getResponse().getContentAsString());
    return json.get("accessToken").asText();
  }

  // --- audit trail (stubbed audit-service) ---

  private static MockHttpServletRequestBuilder fromClient(
      MockHttpServletRequestBuilder builder, String requestId) {
    return builder
        .header("X-Forwarded-For", CLIENT_IP + ", 10.0.0.1")
        .header("X-Request-ID", requestId)
        .header("User-Agent", "audit-it");
  }

  private List<JsonNode> auditBodies() throws Exception {
    List<JsonNode> bodies = new ArrayList<>();
    for (ServeEvent event : auditService.getAllServeEvents()) {
      if (event.getRequest().getUrl().equals(AUDIT_PATH)) {
        bodies.add(objectMapper.readTree(event.getRequest().getBodyAsString()));
      }
    }
    return bodies;
  }

  private Optional<JsonNode> findAudit(String action, String requestId) throws Exception {
    return auditBodies().stream()
        .filter(b -> action.equals(b.path("action").asText()))
        .filter(b -> requestId.equals(b.path("requestId").asText()))
        .findFirst();
  }

  /** Waits for the async emitter and asserts the who/what/where fields shared by every event. */
  private JsonNode awaitAudit(String action, String requestId, String outcome) throws Exception {
    await().atMost(Duration.ofSeconds(5)).until(() -> findAudit(action, requestId).isPresent());
    JsonNode body = findAudit(action, requestId).orElseThrow();
    assertThat(body.path("outcome").asText()).isEqualTo(outcome);
    assertThat(body.path("ipAddress").asText()).isEqualTo(CLIENT_IP);
    assertThat(body.path("requestId").asText()).isEqualTo(requestId);
    assertThat(body.path("userAgent").asText()).isEqualTo("audit-it");
    assertThat(body.path("serviceName").asText()).isEqualTo("auth-service");
    assertThat(body.path("userId").asText()).isNotBlank();
    assertThat(body.path("resourceType").asText()).isNotBlank();
    assertThat(body.path("resourceId").asText()).isNotBlank();
    assertThat(body.path("timestamp").asText()).endsWith("Z");
    assertThat(action).matches("^[a-z]+(\\.[a-z_]+)*$");
    auditService.verify(
        postRequestedFor(urlEqualTo(AUDIT_PATH))
            .withHeader("X-Audit-Token", equalTo("test-audit-token"))
            .withHeader("X-Request-ID", equalTo(requestId)));
    return body;
  }

  private double auditFailures() {
    return meterRegistry.find("audit.emit.failures").counters().stream()
        .mapToDouble(Counter::count)
        .sum();
  }

  private String userId(String email) {
    return userRepository.findByEmail(email).orElseThrow().getId().toString();
  }

  private JsonNode loginJson(String email, String password) throws Exception {
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

  private String createAdminAndLogin() throws Exception {
    User admin = new User();
    admin.setEmail("audit-admin@otterworks.dev");
    admin.setPasswordHash(passwordEncoder.encode("admin123"));
    admin.setDisplayName("Audit Admin");
    admin.setRoles(Set.of(User.Role.ADMIN, User.Role.USER));
    userRepository.save(admin);
    return loginJson("audit-admin@otterworks.dev", "admin123").get("accessToken").asText();
  }

  @Test
  void audit_loginSuccess() throws Exception {
    createTestUser("audit-login@otterworks.dev", "password123", "Audit Login");

    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/login"), "req-login-ok")
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"email\": \"audit-login@otterworks.dev\", \"password\": \"password123\"}"))
        .andExpect(status().isOk());

    JsonNode event = awaitAudit("auth.login.success", "req-login-ok", "success");
    String id = userId("audit-login@otterworks.dev");
    assertThat(event.path("userId").asText()).isEqualTo(id);
    assertThat(event.path("actorEmail").asText()).isEqualTo("audit-login@otterworks.dev");
    assertThat(event.path("actorType").asText()).isEqualTo("user");
    assertThat(event.path("resourceType").asText()).isEqualTo("user");
    assertThat(event.path("resourceId").asText()).isEqualTo(id);
  }

  @Test
  void audit_loginFailure_badPassword() throws Exception {
    createTestUser("audit-bad@otterworks.dev", "password123", "Audit Bad");

    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/login"), "req-login-badpw")
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"email\": \"audit-bad@otterworks.dev\", \"password\": \"wrongpassword\"}"))
        .andExpect(status().isBadRequest());

    JsonNode event = awaitAudit("auth.login.failure", "req-login-badpw", "failure");
    assertThat(event.path("userId").asText()).isEqualTo("anonymous");
    assertThat(event.path("actorType").asText()).isEqualTo("anonymous");
    assertThat(event.path("resourceId").asText()).isEqualTo(userId("audit-bad@otterworks.dev"));
    assertThat(event.path("details").path("reason").asText()).isEqualTo("bad_password");
    assertThat(event.path("details").path("attemptedEmail").asText())
        .isEqualTo("audit-bad@otterworks.dev");
    assertThat(event.toString()).doesNotContain("wrongpassword");
  }

  @Test
  void audit_loginFailure_unknownEmail() throws Exception {
    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/login"), "req-login-unknown")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\": \"ghost@otterworks.dev\", \"password\": \"password123\"}"))
        .andExpect(status().isBadRequest());

    JsonNode event = awaitAudit("auth.login.failure", "req-login-unknown", "failure");
    assertThat(event.path("userId").asText()).isEqualTo("anonymous");
    assertThat(event.path("resourceId").asText()).isEqualTo("unknown");
    assertThat(event.path("details").path("reason").asText()).isEqualTo("unknown_user");
    assertThat(event.path("details").path("attemptedEmail").asText())
        .isEqualTo("ghost@otterworks.dev");
  }

  @Test
  void audit_registerAndDefaultRoleAssignment() throws Exception {
    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/register"), "req-register")
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"email\": \"audit-reg@otterworks.dev\", \"password\": \"password123\", \"displayName\": \"Reg\"}"))
        .andExpect(status().isCreated());

    String id = userId("audit-reg@otterworks.dev");
    JsonNode register = awaitAudit("auth.user.register", "req-register", "success");
    assertThat(register.path("userId").asText()).isEqualTo(id);
    assertThat(register.path("resourceId").asText()).isEqualTo(id);

    JsonNode roles = awaitAudit("permission.change", "req-register", "success");
    assertThat(roles.path("resourceType").asText()).isEqualTo("user");
    assertThat(roles.path("resourceId").asText()).isEqualTo(id);
    assertThat(roles.path("details").path("before").asText()).isEmpty();
    assertThat(roles.path("details").path("after").asText()).isEqualTo("USER");
  }

  @Test
  void audit_logout() throws Exception {
    String accessToken =
        registerAndGetAccessToken("audit-logout@otterworks.dev", "password123", "Logout");

    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/logout"), "req-logout")
                .header("Authorization", "Bearer " + accessToken))
        .andExpect(status().isNoContent());

    JsonNode event = awaitAudit("auth.logout", "req-logout", "success");
    String id = userId("audit-logout@otterworks.dev");
    assertThat(event.path("userId").asText()).isEqualTo(id);
    assertThat(event.path("resourceId").asText()).isEqualTo(id);
  }

  @Test
  void audit_tokenRefreshThenReuseIsDenied() throws Exception {
    MvcResult registered =
        mockMvc
            .perform(
                post("/api/v1/auth/register")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(
                        "{\"email\": \"audit-refresh@otterworks.dev\", \"password\": \"password123\", \"displayName\": \"R\"}"))
            .andExpect(status().isCreated())
            .andReturn();
    String refreshToken =
        objectMapper
            .readTree(registered.getResponse().getContentAsString())
            .get("refreshToken")
            .asText();
    String id = userId("audit-refresh@otterworks.dev");

    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/refresh"), "req-refresh-ok")
                .header("Authorization", "Bearer " + refreshToken))
        .andExpect(status().isOk());
    JsonNode rotated = awaitAudit("auth.token.refresh", "req-refresh-ok", "success");
    assertThat(rotated.path("userId").asText()).isEqualTo(id);
    assertThat(rotated.path("resourceId").asText()).isEqualTo(id);

    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/refresh"), "req-refresh-reused")
                .header("Authorization", "Bearer " + refreshToken))
        .andExpect(status().isBadRequest());
    JsonNode denied = awaitAudit("auth.token.refresh_denied", "req-refresh-reused", "denied");
    assertThat(denied.path("userId").asText()).isEqualTo(id);
    assertThat(denied.path("details").path("reason").asText()).isEqualTo("revoked_or_reused");

    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/refresh"), "req-refresh-garbage")
                .header("Authorization", "Bearer not-a-jwt"))
        .andExpect(status().isUnauthorized());
    JsonNode invalid = awaitAudit("auth.token.refresh_denied", "req-refresh-garbage", "denied");
    assertThat(invalid.path("userId").asText()).isEqualTo("anonymous");
    assertThat(invalid.path("details").path("reason").asText()).isEqualTo("invalid_token");
  }

  @Test
  void audit_changePassword_successAndFailure() throws Exception {
    String accessToken = registerAndGetAccessToken("audit-pw@otterworks.dev", "password123", "PW");
    String id = userId("audit-pw@otterworks.dev");

    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/change-password"), "req-pw-bad")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"currentPassword\": \"nope12345\", \"newPassword\": \"newpassword456\"}"))
        .andExpect(status().isBadRequest());
    JsonNode failed = awaitAudit("auth.credential.change", "req-pw-bad", "failure");
    assertThat(failed.path("userId").asText()).isEqualTo(id);
    assertThat(failed.path("details").path("reason").asText())
        .isEqualTo("current_password_mismatch");

    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/change-password"), "req-pw-ok")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"currentPassword\": \"password123\", \"newPassword\": \"newpassword456\"}"))
        .andExpect(status().isNoContent());
    JsonNode changed = awaitAudit("auth.credential.change", "req-pw-ok", "success");
    assertThat(changed.path("userId").asText()).isEqualTo(id);
    assertThat(changed.path("resourceId").asText()).isEqualTo(id);
  }

  @Test
  void audit_profileEmailChange_successAndConflict() throws Exception {
    String accessToken =
        registerAndGetAccessToken("audit-email@otterworks.dev", "password123", "Email");
    createTestUser("audit-taken@otterworks.dev", "password123", "Taken");
    String id = userId("audit-email@otterworks.dev");

    mockMvc
        .perform(
            fromClient(put("/api/v1/auth/profile"), "req-email-taken")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\": \"audit-taken@otterworks.dev\"}"))
        .andExpect(status().isBadRequest());
    JsonNode failed = awaitAudit("auth.profile.email_change", "req-email-taken", "failure");
    assertThat(failed.path("userId").asText()).isEqualTo(id);
    assertThat(failed.path("details").path("reason").asText()).isEqualTo("email_taken");

    mockMvc
        .perform(
            fromClient(put("/api/v1/auth/profile"), "req-email-ok")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\": \"audit-email-new@otterworks.dev\"}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.email").value("audit-email-new@otterworks.dev"));
    JsonNode changed = awaitAudit("auth.profile.email_change", "req-email-ok", "success");
    assertThat(changed.path("resourceId").asText()).isEqualTo(id);
    assertThat(changed.path("details").path("previousEmail").asText())
        .isEqualTo("audit-email@otterworks.dev");
    assertThat(changed.path("details").path("newEmail").asText())
        .isEqualTo("audit-email-new@otterworks.dev");
  }

  @Test
  void updateProfile_shouldRejectBlankEmail() throws Exception {
    String accessToken =
        registerAndGetAccessToken("blank-email@otterworks.dev", "password123", "Blank");

    mockMvc
        .perform(
            put("/api/v1/auth/profile")
                .header("Authorization", "Bearer " + accessToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\": \"\"}"))
        .andExpect(status().isBadRequest());
    assertThat(userRepository.findByEmail("blank-email@otterworks.dev")).isPresent();
  }

  @Test
  void audit_lookupUserById() throws Exception {
    String accessToken =
        registerAndGetAccessToken("audit-byid@otterworks.dev", "password123", "ById");
    String id = userId("audit-byid@otterworks.dev");

    mockMvc
        .perform(
            fromClient(get("/api/v1/auth/users/by-id/" + id), "req-export-byid")
                .header("Authorization", "Bearer " + accessToken))
        .andExpect(status().isOk());
    JsonNode event = awaitAudit("export", "req-export-byid", "success");
    assertThat(event.path("resourceType").asText()).isEqualTo("user_directory");
    assertThat(event.path("resourceId").asText()).isEqualTo(id);
  }

  @Test
  void audit_adminRoleChange() throws Exception {
    String adminToken = createAdminAndLogin();
    createTestUser("audit-promote@otterworks.dev", "password123", "Promote");
    String targetId = userId("audit-promote@otterworks.dev");

    mockMvc
        .perform(
            fromClient(put("/api/v1/auth/users/" + targetId + "/roles"), "req-roles")
                .header("Authorization", "Bearer " + adminToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"roles\": [\"USER\", \"EDITOR\"]}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.roles.length()").value(2));

    JsonNode event = awaitAudit("permission.change", "req-roles", "success");
    assertThat(event.path("userId").asText()).isEqualTo(userId("audit-admin@otterworks.dev"));
    assertThat(event.path("actorType").asText()).isEqualTo("admin");
    assertThat(event.path("resourceType").asText()).isEqualTo("user");
    assertThat(event.path("resourceId").asText()).isEqualTo(targetId);
    assertThat(event.path("details").path("before").asText()).isEqualTo("USER");
    assertThat(event.path("details").path("after").asText()).isEqualTo("EDITOR,USER");
  }

  @Test
  void roleChange_requiresAdmin() throws Exception {
    String userToken =
        registerAndGetAccessToken("audit-nonadmin@otterworks.dev", "password123", "Non Admin");

    mockMvc
        .perform(
            put("/api/v1/auth/users/" + userId("audit-nonadmin@otterworks.dev") + "/roles")
                .header("Authorization", "Bearer " + userToken)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"roles\": [\"ADMIN\"]}"))
        .andExpect(status().isForbidden());
    assertThat(userRepository.findByEmail("audit-nonadmin@otterworks.dev").orElseThrow().getRoles())
        .containsExactly(User.Role.USER);
  }

  @Test
  void audit_userDirectoryExport_listAndLookup() throws Exception {
    String adminToken = createAdminAndLogin();
    String adminId = userId("audit-admin@otterworks.dev");
    createTestUser("audit-target@otterworks.dev", "password123", "Target");

    mockMvc
        .perform(
            fromClient(get("/api/v1/auth/users"), "req-export-list")
                .header("Authorization", "Bearer " + adminToken)
                .param("page", "0")
                .param("size", "10"))
        .andExpect(status().isOk());
    JsonNode list = awaitAudit("export", "req-export-list", "success");
    assertThat(list.path("userId").asText()).isEqualTo(adminId);
    assertThat(list.path("actorType").asText()).isEqualTo("admin");
    assertThat(list.path("resourceType").asText()).isEqualTo("user_directory");
    assertThat(list.path("resourceId").asText()).isEqualTo("all");
    assertThat(list.path("details").path("returned").asText()).isEqualTo("2");

    mockMvc
        .perform(
            fromClient(get("/api/v1/auth/users/lookup"), "req-export-lookup")
                .header("Authorization", "Bearer " + adminToken)
                .param("email", "audit-target@otterworks.dev"))
        .andExpect(status().isOk());
    JsonNode lookup = awaitAudit("export", "req-export-lookup", "success");
    assertThat(lookup.path("userId").asText()).isEqualTo(adminId);
    assertThat(lookup.path("resourceType").asText()).isEqualTo("user_directory");
    assertThat(lookup.path("resourceId").asText()).isEqualTo(userId("audit-target@otterworks.dev"));
    assertThat(lookup.path("details").path("lookupEmail").asText())
        .isEqualTo("audit-target@otterworks.dev");
  }

  @Test
  void audit_loginStillSucceedsWhenAuditServiceReturns5xx() throws Exception {
    createTestUser("audit-down@otterworks.dev", "password123", "Down");
    auditService.stubFor(WireMock.post(AUDIT_PATH).willReturn(aResponse().withStatus(503)));
    double failuresBefore = auditFailures();

    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/login"), "req-audit-5xx")
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"email\": \"audit-down@otterworks.dev\", \"password\": \"password123\"}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.accessToken").isNotEmpty());

    await().atMost(Duration.ofSeconds(5)).until(() -> auditFailures() > failuresBefore);
    // One bounded retry: two attempts for the single login event.
    await()
        .atMost(Duration.ofSeconds(5))
        .untilAsserted(
            () ->
                auditService.verify(
                    2,
                    postRequestedFor(urlEqualTo(AUDIT_PATH))
                        .withHeader("X-Request-ID", equalTo("req-audit-5xx"))));
  }

  @Test
  void audit_loginStillSucceedsQuicklyWhenAuditServiceTimesOut() throws Exception {
    createTestUser("audit-slow@otterworks.dev", "password123", "Slow");
    auditService.stubFor(
        WireMock.post(AUDIT_PATH).willReturn(aResponse().withStatus(201).withFixedDelay(5000)));
    double failuresBefore = auditFailures();

    long start = System.nanoTime();
    mockMvc
        .perform(
            fromClient(post("/api/v1/auth/login"), "req-audit-timeout")
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"email\": \"audit-slow@otterworks.dev\", \"password\": \"password123\"}"))
        .andExpect(status().isOk());
    long elapsedMs = (System.nanoTime() - start) / 1_000_000;

    // Audit timeout is 500ms in the test profile; the login must not wait for it.
    assertThat(elapsedMs).isLessThan(3000);
    await().atMost(Duration.ofSeconds(5)).until(() -> auditFailures() > failuresBefore);
  }

  @Test
  void audit_eventsNeverContainPasswordsOrTokens() throws Exception {
    MvcResult registered =
        mockMvc
            .perform(
                post("/api/v1/auth/register")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(
                        "{\"email\": \"audit-secret@otterworks.dev\", \"password\": \"S3cretPassw0rd!\", \"displayName\": \"S\"}"))
            .andExpect(status().isCreated())
            .andReturn();
    JsonNode reg = objectMapper.readTree(registered.getResponse().getContentAsString());
    mockMvc
        .perform(
            post("/api/v1/auth/refresh")
                .header("Authorization", "Bearer " + reg.get("refreshToken").asText()))
        .andExpect(status().isOk());
    JsonNode login = loginJson("audit-secret@otterworks.dev", "S3cretPassw0rd!");
    mockMvc
        .perform(
            post("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"email\": \"audit-secret@otterworks.dev\", \"password\": \"Wr0ngPassw0rd!\"}"))
        .andExpect(status().isBadRequest());
    mockMvc
        .perform(
            post("/api/v1/auth/change-password")
                .header("Authorization", "Bearer " + login.get("accessToken").asText())
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"currentPassword\": \"S3cretPassw0rd!\", \"newPassword\": \"N3wSecretPass!\"}"))
        .andExpect(status().isNoContent());

    await().atMost(Duration.ofSeconds(5)).until(() -> auditBodies().size() >= 6);
    List<String> secrets =
        List.of(
            "S3cretPassw0rd!",
            "Wr0ngPassw0rd!",
            "N3wSecretPass!",
            reg.get("accessToken").asText(),
            reg.get("refreshToken").asText(),
            login.get("accessToken").asText(),
            login.get("refreshToken").asText(),
            "$2a$");
    for (JsonNode body : auditBodies()) {
      String raw = body.toString();
      for (String secret : secrets) {
        assertThat(raw).doesNotContain(secret);
      }
      for (Iterator<String> fields = body.fieldNames(); fields.hasNext(); ) {
        assertThat(fields.next().toLowerCase()).doesNotContain("password").doesNotContain("token");
      }
    }
  }
}
