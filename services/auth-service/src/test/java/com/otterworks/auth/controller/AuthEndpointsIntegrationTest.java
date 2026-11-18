package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.repository.UserSettingsRepository;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class AuthEndpointsIntegrationTest {

  @Autowired private MockMvc mockMvc;
  @Autowired private ObjectMapper objectMapper;
  @Autowired private UserRepository userRepository;
  @Autowired private RefreshTokenRepository refreshTokenRepository;
  @Autowired private UserSettingsRepository userSettingsRepository;

  @BeforeEach
  void setUp() {
    userSettingsRepository.deleteAll();
    refreshTokenRepository.deleteAll();
    userRepository.deleteAll();
  }

  private JsonNode register(String email) throws Exception {
    String body =
        String.format(
            "{\"email\": \"%s\", \"password\": \"password123\", \"displayName\": \"Otter\"}",
            email);
    String json =
        mockMvc
            .perform(
                post("/api/v1/auth/register").contentType(MediaType.APPLICATION_JSON).content(body))
            .andExpect(status().isCreated())
            .andReturn()
            .getResponse()
            .getContentAsString();
    return objectMapper.readTree(json);
  }

  private static String bearer(JsonNode auth, String field) {
    return "Bearer " + auth.get(field).asText();
  }

  @Test
  void settings_getShouldReturnDefaultsAndPersistThem() throws Exception {
    JsonNode auth = register("settings@otterworks.dev");

    mockMvc
        .perform(get("/api/v1/settings").header("Authorization", bearer(auth, "accessToken")))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.notificationEmail").value(true))
        .andExpect(jsonPath("$.notificationInApp").value(true))
        .andExpect(jsonPath("$.notificationDesktop").value(false))
        .andExpect(jsonPath("$.theme").value("system"))
        .andExpect(jsonPath("$.language").value("en"));

    assertThat(userSettingsRepository.count()).isEqualTo(1);
  }

  @Test
  void settings_patchShouldApplyPartialUpdateAndPersist() throws Exception {
    JsonNode auth = register("patch@otterworks.dev");
    String token = bearer(auth, "accessToken");

    mockMvc
        .perform(
            patch("/api/v1/settings")
                .header("Authorization", token)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"theme\": \"dark\", \"notificationDesktop\": true}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.theme").value("dark"))
        .andExpect(jsonPath("$.notificationDesktop").value(true))
        .andExpect(jsonPath("$.language").value("en"));

    mockMvc
        .perform(
            patch("/api/v1/settings")
                .header("Authorization", token)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"language\": \"fr\"}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.theme").value("dark"))
        .andExpect(jsonPath("$.language").value("fr"));

    mockMvc
        .perform(get("/api/v1/settings").header("Authorization", token))
        .andExpect(jsonPath("$.theme").value("dark"))
        .andExpect(jsonPath("$.language").value("fr"))
        .andExpect(jsonPath("$.notificationDesktop").value(true));
  }

  @Test
  void settings_shouldRejectUnauthenticatedRequest() throws Exception {
    mockMvc.perform(get("/api/v1/settings")).andExpect(status().isForbidden());
  }

  @Test
  void logout_shouldRevokeRefreshTokens() throws Exception {
    JsonNode auth = register("logout@otterworks.dev");

    mockMvc
        .perform(post("/api/v1/auth/logout").header("Authorization", bearer(auth, "accessToken")))
        .andExpect(status().isNoContent());

    assertThat(refreshTokenRepository.findAll()).allMatch(t -> t.isRevoked());
    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", bearer(auth, "refreshToken")))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.message").value("Invalid or revoked refresh token"));
  }

  @Test
  void refresh_shouldRejectReusedRefreshToken() throws Exception {
    JsonNode auth = register("reuse@otterworks.dev");
    String refresh = bearer(auth, "refreshToken");

    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", refresh))
        .andExpect(status().isOk());
    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", refresh))
        .andExpect(status().isBadRequest());
  }

  @Test
  void refresh_shouldRejectAccessToken() throws Exception {
    JsonNode auth = register("access-as-refresh@otterworks.dev");

    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", bearer(auth, "accessToken")))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.message").value("Token is not a refresh token"));
  }

  @Test
  void refresh_shouldReturn401ForMalformedToken() throws Exception {
    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", "Bearer not.a.jwt"))
        .andExpect(status().isUnauthorized())
        .andExpect(jsonPath("$.message").value("Invalid or expired token"));
  }

  @Test
  void refreshToken_shouldNotAuthenticateProtectedEndpoints() throws Exception {
    JsonNode auth = register("refresh-as-access@otterworks.dev");

    mockMvc
        .perform(get("/api/v1/auth/profile").header("Authorization", bearer(auth, "refreshToken")))
        .andExpect(status().isForbidden());
  }

  @Test
  void lookupByEmail_shouldReturnPublicFields() throws Exception {
    JsonNode target = register("target@otterworks.dev");
    JsonNode caller = register("caller@otterworks.dev");

    mockMvc
        .perform(
            get("/api/v1/auth/users/lookup")
                .param("email", "target@otterworks.dev")
                .header("Authorization", bearer(caller, "accessToken")))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.id").value(target.get("user").get("id").asText()))
        .andExpect(jsonPath("$.email").value("target@otterworks.dev"))
        .andExpect(jsonPath("$.displayName").value("Otter"))
        .andExpect(jsonPath("$.roles").doesNotExist());
  }

  @Test
  void lookupByEmail_shouldReturn400ForUnknownEmail() throws Exception {
    JsonNode caller = register("caller2@otterworks.dev");

    mockMvc
        .perform(
            get("/api/v1/auth/users/lookup")
                .param("email", "ghost@otterworks.dev")
                .header("Authorization", bearer(caller, "accessToken")))
        .andExpect(status().isBadRequest());
  }

  @Test
  void lookupById_shouldReturnUser() throws Exception {
    JsonNode target = register("byid@otterworks.dev");
    String id = target.get("user").get("id").asText();

    mockMvc
        .perform(
            get("/api/v1/auth/users/by-id/" + id)
                .header("Authorization", bearer(target, "accessToken")))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.email").value("byid@otterworks.dev"));
  }

  @Test
  void lookupById_shouldReturn400ForUnknownId() throws Exception {
    JsonNode caller = register("byid2@otterworks.dev");

    mockMvc
        .perform(
            get("/api/v1/auth/users/by-id/" + UUID.randomUUID())
                .header("Authorization", bearer(caller, "accessToken")))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.message").value("User not found"));
  }

  @Test
  void lookup_shouldRequireAuthentication() throws Exception {
    mockMvc
        .perform(get("/api/v1/auth/users/lookup").param("email", "a@otterworks.dev"))
        .andExpect(status().isForbidden());
  }

  @Test
  void changePassword_shouldRejectWrongCurrentPassword() throws Exception {
    JsonNode auth = register("wrongpw@otterworks.dev");

    mockMvc
        .perform(
            post("/api/v1/auth/change-password")
                .header("Authorization", bearer(auth, "accessToken"))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"currentPassword\": \"nope\", \"newPassword\": \"newpassword456\"}"))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.message").value("Current password is incorrect"));
  }

  @Test
  void changePassword_shouldRevokeExistingRefreshTokens() throws Exception {
    JsonNode auth = register("revoke@otterworks.dev");

    mockMvc
        .perform(
            post("/api/v1/auth/change-password")
                .header("Authorization", bearer(auth, "accessToken"))
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"currentPassword\": \"password123\", \"newPassword\": \"newpassword456\"}"))
        .andExpect(status().isNoContent());

    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", bearer(auth, "refreshToken")))
        .andExpect(status().isBadRequest());
  }

  @Test
  void register_shouldReportFieldValidationErrors() throws Exception {
    mockMvc
        .perform(
            post("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\": \"a@otterworks.dev\", \"password\": \"short\"}"))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.message").value(org.hamcrest.Matchers.containsString("password")))
        .andExpect(
            jsonPath("$.message").value(org.hamcrest.Matchers.containsString("displayName")));
  }
}
