package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.repository.UserSettingsRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

/** QA audit: black-box MockMvc coverage of auth + settings edge cases (H2, full Spring context). */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class AuthQaIntegrationTest {

  private static final String PASSWORD = "OtterQa123!";

  @Autowired private MockMvc mockMvc;
  @Autowired private ObjectMapper objectMapper;
  @Autowired private UserRepository userRepository;
  @Autowired private RefreshTokenRepository refreshTokenRepository;
  @Autowired private UserSettingsRepository settingsRepository;

  @BeforeEach
  void setUp() {
    settingsRepository.deleteAll();
    refreshTokenRepository.deleteAll();
    userRepository.deleteAll();
  }

  private JsonNode register(String email) throws Exception {
    MvcResult result =
        mockMvc
            .perform(
                post("/api/v1/auth/register")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(
                        String.format(
                            "{\"email\":\"%s\",\"password\":\"%s\",\"displayName\":\"QA User\"}",
                            email, PASSWORD)))
            .andExpect(status().isCreated())
            .andReturn();
    return objectMapper.readTree(result.getResponse().getContentAsString());
  }

  private String bearer(JsonNode auth) {
    return "Bearer " + auth.get("accessToken").asText();
  }

  private String refreshBearer(JsonNode auth) {
    return "Bearer " + auth.get("refreshToken").asText();
  }

  private org.springframework.test.web.servlet.ResultActions login(String email, String pw)
      throws Exception {
    return mockMvc.perform(
        post("/api/v1/auth/login")
            .contentType(MediaType.APPLICATION_JSON)
            .content(String.format("{\"email\":\"%s\",\"password\":\"%s\"}", email, pw)));
  }

  // ── settings ─────────────────────────────────────────────────

  @Test
  void settings_defaultsAreCreatedOnFirstRead() throws Exception {
    JsonNode auth = register("settings-defaults@otterworks.dev");

    mockMvc
        .perform(get("/api/v1/settings").header("Authorization", bearer(auth)))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.notificationEmail").value(true))
        .andExpect(jsonPath("$.notificationInApp").value(true))
        .andExpect(jsonPath("$.notificationDesktop").value(false))
        .andExpect(jsonPath("$.theme").value("system"))
        .andExpect(jsonPath("$.language").value("en"));
  }

  @Test
  void settings_patchPersistsAndIsPartial() throws Exception {
    JsonNode auth = register("settings-patch@otterworks.dev");

    mockMvc
        .perform(
            patch("/api/v1/settings")
                .header("Authorization", bearer(auth))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"notificationDesktop\":true,\"theme\":\"dark\"}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.notificationDesktop").value(true))
        .andExpect(jsonPath("$.theme").value("dark"));

    mockMvc
        .perform(
            patch("/api/v1/settings")
                .header("Authorization", bearer(auth))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"notificationEmail\":false}"))
        .andExpect(status().isOk());

    mockMvc
        .perform(get("/api/v1/settings").header("Authorization", bearer(auth)))
        .andExpect(jsonPath("$.notificationDesktop").value(true))
        .andExpect(jsonPath("$.notificationEmail").value(false))
        .andExpect(jsonPath("$.notificationInApp").value(true))
        .andExpect(jsonPath("$.theme").value("dark"));
  }

  @Test
  void settings_areIsolatedPerUser() throws Exception {
    JsonNode alice = register("settings-alice@otterworks.dev");
    JsonNode bob = register("settings-bob@otterworks.dev");

    mockMvc
        .perform(
            patch("/api/v1/settings")
                .header("Authorization", bearer(alice))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"theme\":\"dark\"}"))
        .andExpect(status().isOk());

    mockMvc
        .perform(get("/api/v1/settings").header("Authorization", bearer(bob)))
        .andExpect(jsonPath("$.theme").value("system"));
  }

  @Test
  void settings_requireAuthentication() throws Exception {
    mockMvc.perform(get("/api/v1/settings")).andExpect(status().is4xxClientError());
    mockMvc
        .perform(patch("/api/v1/settings").contentType(MediaType.APPLICATION_JSON).content("{}"))
        .andExpect(status().is4xxClientError());
  }

  @Test
  void settings_refreshTokenIsNotAcceptedAsAccessToken() throws Exception {
    JsonNode auth = register("settings-refresh@otterworks.dev");

    mockMvc
        .perform(get("/api/v1/settings").header("Authorization", refreshBearer(auth)))
        .andExpect(status().is4xxClientError());
  }

  @Test
  @Disabled("QA-AUTH-05: theme longer than the VARCHAR(10) column is not validated and returns 500")
  void settings_overlongThemeIsRejectedAs400() throws Exception {
    JsonNode auth = register("settings-long@otterworks.dev");

    mockMvc
        .perform(
            patch("/api/v1/settings")
                .header("Authorization", bearer(auth))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"theme\":\"midnight-blue-high-contrast\"}"))
        .andExpect(status().isBadRequest());
  }

  @Test
  @Disabled("QA-AUTH-05: theme/language accept arbitrary values (no allow-list)")
  void settings_unknownThemeValueIsRejected() throws Exception {
    JsonNode auth = register("settings-enum@otterworks.dev");

    mockMvc
        .perform(
            patch("/api/v1/settings")
                .header("Authorization", bearer(auth))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"theme\":\"neon\"}"))
        .andExpect(status().isBadRequest());
  }

  // ── profile ──────────────────────────────────────────────────

  @Test
  void profile_putPersistsAcrossReads() throws Exception {
    JsonNode auth = register("profile-put@otterworks.dev");

    mockMvc
        .perform(
            put("/api/v1/auth/profile")
                .header("Authorization", bearer(auth))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"displayName\":\"Renamed Otter\"}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.displayName").value("Renamed Otter"));

    mockMvc
        .perform(get("/api/v1/auth/profile").header("Authorization", bearer(auth)))
        .andExpect(jsonPath("$.displayName").value("Renamed Otter"))
        .andExpect(jsonPath("$.email").value("profile-put@otterworks.dev"))
        .andExpect(jsonPath("$.roles[0]").value("USER"));
  }

  @Test
  void profile_putRejectsEmptyDisplayName() throws Exception {
    JsonNode auth = register("profile-empty@otterworks.dev");

    mockMvc
        .perform(
            put("/api/v1/auth/profile")
                .header("Authorization", bearer(auth))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"displayName\":\"\"}"))
        .andExpect(status().isBadRequest())
        .andExpect(
            jsonPath("$.message").value(org.hamcrest.Matchers.containsString("displayName")));
  }

  @Test
  void profile_responseNeverExposesPasswordHash() throws Exception {
    JsonNode auth = register("profile-hash@otterworks.dev");

    String body =
        mockMvc
            .perform(get("/api/v1/auth/profile").header("Authorization", bearer(auth)))
            .andReturn()
            .getResponse()
            .getContentAsString();
    assertThat(body).doesNotContain("passwordHash").doesNotContain("$2a$");
  }

  @Test
  @Disabled(
      "QA-AUTH-01: web client sends PATCH /api/v1/auth/profile but only PUT is mapped; returns 500")
  void profile_patchIsSupportedBecauseWebClientUsesPatch() throws Exception {
    JsonNode auth = register("profile-patch@otterworks.dev");

    mockMvc
        .perform(
            patch("/api/v1/auth/profile")
                .header("Authorization", bearer(auth))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"displayName\":\"Patched Otter\"}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.displayName").value("Patched Otter"));
  }

  @Test
  @Disabled(
      "QA-AUTH-06: unauthenticated requests get 403 instead of 401 (no AuthenticationEntryPoint)")
  void profile_unauthenticatedReturns401() throws Exception {
    mockMvc.perform(get("/api/v1/auth/profile")).andExpect(status().isUnauthorized());
  }

  // ── register / login ─────────────────────────────────────────

  @Test
  @Disabled(
      "QA-AUTH-02: email uniqueness is case-sensitive; CaseTest@ and casetest@ both register (201)")
  void register_duplicateEmailIsCaseInsensitive() throws Exception {
    register("CaseTest@otterworks.dev");

    mockMvc
        .perform(
            post("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"email\":\"casetest@otterworks.dev\",\"password\":\"OtterQa123!\","
                        + "\"displayName\":\"Dup\"}"))
        .andExpect(status().isBadRequest());
  }

  @Test
  void register_duplicateEmailReturnsClearMessage() throws Exception {
    register("dup@otterworks.dev");

    mockMvc
        .perform(
            post("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"email\":\"dup@otterworks.dev\",\"password\":\"OtterQa123!\","
                        + "\"displayName\":\"Dup\"}"))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.message").value("Email already registered"));
  }

  @Test
  @Disabled("QA-AUTH-04: malformed JSON body is mapped to 500 by the catch-all exception handler")
  void register_malformedJsonReturns400() throws Exception {
    mockMvc
        .perform(
            post("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\": \"x@y.dev\", "))
        .andExpect(status().isBadRequest());
  }

  @Test
  void register_validationErrorNamesEachField() throws Exception {
    mockMvc
        .perform(
            post("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"email\":\"bad\",\"password\":\"short\",\"displayName\":\"\"}"))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.message").value(org.hamcrest.Matchers.containsString("email")))
        .andExpect(jsonPath("$.message").value(org.hamcrest.Matchers.containsString("password")))
        .andExpect(
            jsonPath("$.message").value(org.hamcrest.Matchers.containsString("displayName")));
  }

  @Test
  void login_unknownEmailAndWrongPasswordAreIndistinguishable() throws Exception {
    register("enum@otterworks.dev");

    String wrong =
        login("enum@otterworks.dev", "WrongPass123!")
            .andExpect(status().isBadRequest())
            .andReturn()
            .getResponse()
            .getContentAsString();
    String unknown =
        login("ghost@otterworks.dev", "WrongPass123!")
            .andExpect(status().isBadRequest())
            .andReturn()
            .getResponse()
            .getContentAsString();

    assertThat(objectMapper.readTree(wrong).get("message").asText())
        .isEqualTo(objectMapper.readTree(unknown).get("message").asText())
        .isEqualTo("Invalid credentials");
  }

  @Test
  @Disabled(
      "QA-AUTH-03: no account lockout or login throttling; correct password still succeeds after 10 failures")
  void login_isLockedOutAfterRepeatedFailures() throws Exception {
    register("lockout@otterworks.dev");
    for (int i = 0; i < 10; i++) {
      login("lockout@otterworks.dev", "WrongPass123!").andExpect(status().isBadRequest());
    }

    login("lockout@otterworks.dev", PASSWORD).andExpect(status().is(423));
  }

  @Test
  void login_updatesLastLoginAt() throws Exception {
    JsonNode auth = register("lastlogin@otterworks.dev");
    mockMvc
        .perform(get("/api/v1/auth/profile").header("Authorization", bearer(auth)))
        .andExpect(jsonPath("$.lastLoginAt").doesNotExist());

    login("lastlogin@otterworks.dev", PASSWORD).andExpect(status().isOk());

    mockMvc
        .perform(get("/api/v1/auth/profile").header("Authorization", bearer(auth)))
        .andExpect(jsonPath("$.lastLoginAt").isNotEmpty());
  }

  // ── refresh / logout / change password ───────────────────────

  @Test
  @Disabled(
      "QA-AUTH-04: refresh without an Authorization header returns 500 (MissingRequestHeaderException)")
  void refresh_withoutAuthorizationHeaderReturns4xx() throws Exception {
    mockMvc.perform(post("/api/v1/auth/refresh")).andExpect(status().is4xxClientError());
  }

  @Test
  void refresh_withGarbageTokenReturns401() throws Exception {
    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", "Bearer not.a.jwt"))
        .andExpect(status().isUnauthorized());
  }

  @Test
  void refresh_withAccessTokenIsRejected() throws Exception {
    JsonNode auth = register("refresh-access@otterworks.dev");

    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", bearer(auth)))
        .andExpect(status().is4xxClientError());
  }

  @Test
  void logout_revokesRefreshTokens() throws Exception {
    JsonNode auth = register("logout@otterworks.dev");

    mockMvc
        .perform(post("/api/v1/auth/logout").header("Authorization", bearer(auth)))
        .andExpect(status().isNoContent());

    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", refreshBearer(auth)))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.message").value("Invalid or revoked refresh token"));
  }

  @Test
  @Disabled(
      "QA-AUTH-07: logout only revokes refresh tokens; the access token stays valid until expiry")
  void logout_invalidatesAccessToken() throws Exception {
    JsonNode auth = register("logout-access@otterworks.dev");

    mockMvc
        .perform(post("/api/v1/auth/logout").header("Authorization", bearer(auth)))
        .andExpect(status().isNoContent());

    mockMvc
        .perform(get("/api/v1/auth/profile").header("Authorization", bearer(auth)))
        .andExpect(status().is4xxClientError());
  }

  @Test
  void changePassword_fullLifecycle() throws Exception {
    JsonNode auth = register("chpw@otterworks.dev");

    mockMvc
        .perform(
            post("/api/v1/auth/change-password")
                .header("Authorization", bearer(auth))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"currentPassword\":\"nope-nope\",\"newPassword\":\"NewOtter123!\"}"))
        .andExpect(status().isBadRequest())
        .andExpect(jsonPath("$.message").value("Current password is incorrect"));

    mockMvc
        .perform(
            post("/api/v1/auth/change-password")
                .header("Authorization", bearer(auth))
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"currentPassword\":\"" + PASSWORD + "\",\"newPassword\":\"short\"}"))
        .andExpect(status().isBadRequest());

    mockMvc
        .perform(
            post("/api/v1/auth/change-password")
                .header("Authorization", bearer(auth))
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"currentPassword\":\"" + PASSWORD + "\",\"newPassword\":\"NewOtter123!\"}"))
        .andExpect(status().isNoContent());

    login("chpw@otterworks.dev", PASSWORD).andExpect(status().isBadRequest());
    login("chpw@otterworks.dev", "NewOtter123!").andExpect(status().isOk());
    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", refreshBearer(auth)))
        .andExpect(status().isBadRequest());
  }

  // ── user lookup ──────────────────────────────────────────────

  @Test
  void lookup_requiresAuthenticationAndFindsByEmailAndId() throws Exception {
    JsonNode alice = register("lookup-alice@otterworks.dev");
    JsonNode bob = register("lookup-bob@otterworks.dev");
    String bobId = bob.get("user").get("id").asText();

    mockMvc
        .perform(get("/api/v1/auth/users/lookup").param("email", "lookup-bob@otterworks.dev"))
        .andExpect(status().is4xxClientError());

    mockMvc
        .perform(
            get("/api/v1/auth/users/lookup")
                .param("email", "lookup-bob@otterworks.dev")
                .header("Authorization", bearer(alice)))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.id").value(bobId))
        .andExpect(jsonPath("$.roles").doesNotExist());

    mockMvc
        .perform(get("/api/v1/auth/users/by-id/" + bobId).header("Authorization", bearer(alice)))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.email").value("lookup-bob@otterworks.dev"));
  }

  @Test
  @Disabled("QA-AUTH-08: unknown email lookup returns 400 (and echoes the email) instead of 404")
  void lookup_unknownEmailReturns404() throws Exception {
    JsonNode alice = register("lookup-404@otterworks.dev");

    mockMvc
        .perform(
            get("/api/v1/auth/users/lookup")
                .param("email", "nobody@otterworks.dev")
                .header("Authorization", bearer(alice)))
        .andExpect(status().isNotFound());
  }
}
