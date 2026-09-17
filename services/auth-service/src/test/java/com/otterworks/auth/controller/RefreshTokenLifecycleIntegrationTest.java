package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.auth.entity.RefreshToken;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.security.JwtTokenProvider;
import io.jsonwebtoken.Claims;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

/**
 * End-to-end refresh-token lifecycle: what a token carries, how rotation invalidates the presented
 * token, and which operations revoke every token a user holds.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class RefreshTokenLifecycleIntegrationTest {

  @Autowired private MockMvc mockMvc;
  @Autowired private ObjectMapper objectMapper;
  @Autowired private UserRepository userRepository;
  @Autowired private RefreshTokenRepository refreshTokenRepository;
  @Autowired private JwtTokenProvider jwtTokenProvider;

  @BeforeEach
  void setUp() {
    refreshTokenRepository.deleteAll();
    userRepository.deleteAll();
  }

  @Test
  void issuedTokens_shouldCarryTheClaimsTheGatewayAndBackendsRead() throws Exception {
    JsonNode tokens = register("claims@otterworks.dev");

    Claims access = jwtTokenProvider.validateAndGetClaims(tokens.get("accessToken").asText());
    assertThat(access.getSubject())
        .isEqualTo(
            userRepository.findByEmail("claims@otterworks.dev").orElseThrow().getId().toString());
    assertThat(access.get("email", String.class)).isEqualTo("claims@otterworks.dev");
    assertThat(access.get("type", String.class)).isEqualTo("access");
    assertThat(access.get("roles", List.class)).containsExactly("USER");

    Claims refresh = jwtTokenProvider.validateAndGetClaims(tokens.get("refreshToken").asText());
    assertThat(refresh.get("type", String.class)).isEqualTo("refresh");
    assertThat(refresh.getId()).isNotBlank();
    assertThat(refresh.get("roles")).isNull();
  }

  @Test
  void register_shouldPersistTheRefreshTokenUnrevoked() throws Exception {
    JsonNode tokens = register("persist@otterworks.dev");
    String jti = jwtTokenProvider.extractJti(tokens.get("refreshToken").asText());

    RefreshToken stored = storedToken(jti);
    UUID userId = userRepository.findByEmail("persist@otterworks.dev").orElseThrow().getId();

    assertThat(stored.isRevoked()).isFalse();
    assertThat(stored.getUser().getId()).isEqualTo(userId);
    assertThat(stored.getExpiresAt()).isAfter(Instant.now());
  }

  @Test
  void refresh_shouldRotateTokensAndRejectTheReusedOne() throws Exception {
    JsonNode tokens = register("rotate@otterworks.dev");
    String firstRefresh = tokens.get("refreshToken").asText();

    MvcResult refreshed =
        mockMvc
            .perform(post("/api/v1/auth/refresh").header("Authorization", "Bearer " + firstRefresh))
            .andExpect(status().isOk())
            .andReturn();
    String secondRefresh =
        objectMapper
            .readTree(refreshed.getResponse().getContentAsString())
            .get("refreshToken")
            .asText();

    assertThat(secondRefresh).isNotEqualTo(firstRefresh);
    assertThat(storedToken(jwtTokenProvider.extractJti(firstRefresh)).isRevoked()).isTrue();
    assertThat(storedToken(jwtTokenProvider.extractJti(secondRefresh)).isRevoked()).isFalse();

    // Replaying the rotated-out token fails; the newly issued one works.
    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", "Bearer " + firstRefresh))
        .andExpect(status().isBadRequest());
    mockMvc
        .perform(post("/api/v1/auth/refresh").header("Authorization", "Bearer " + secondRefresh))
        .andExpect(status().isOk());
  }

  @Test
  void logout_shouldRevokeEveryRefreshTokenOfTheUser() throws Exception {
    JsonNode first = register("logout@otterworks.dev");
    JsonNode second = login("logout@otterworks.dev");

    mockMvc
        .perform(
            post("/api/v1/auth/logout")
                .header("Authorization", "Bearer " + second.get("accessToken").asText()))
        .andExpect(status().isNoContent());

    for (String refreshToken :
        List.of(first.get("refreshToken").asText(), second.get("refreshToken").asText())) {
      mockMvc
          .perform(post("/api/v1/auth/refresh").header("Authorization", "Bearer " + refreshToken))
          .andExpect(status().isBadRequest());
    }
    assertThat(refreshTokenRepository.findAll()).allMatch(RefreshToken::isRevoked);
  }

  @Test
  void changePassword_shouldRevokeEveryRefreshTokenOfTheUser() throws Exception {
    JsonNode tokens = register("changepw-revoke@otterworks.dev");

    mockMvc
        .perform(
            post("/api/v1/auth/change-password")
                .header("Authorization", "Bearer " + tokens.get("accessToken").asText())
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"currentPassword\": \"password123\", \"newPassword\": \"newpassword456\"}"))
        .andExpect(status().isNoContent());

    mockMvc
        .perform(
            post("/api/v1/auth/refresh")
                .header("Authorization", "Bearer " + tokens.get("refreshToken").asText()))
        .andExpect(status().isBadRequest());

    mockMvc
        .perform(
            post("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"email\": \"changepw-revoke@otterworks.dev\","
                        + " \"password\": \"password123\"}"))
        .andExpect(status().isBadRequest());
  }

  @Test
  void accessToken_shouldNotBeAcceptedAsARefreshToken() throws Exception {
    JsonNode tokens = register("wrongtype@otterworks.dev");

    mockMvc
        .perform(
            post("/api/v1/auth/refresh")
                .header("Authorization", "Bearer " + tokens.get("accessToken").asText()))
        .andExpect(status().isBadRequest());
  }

  private RefreshToken storedToken(String jti) {
    return refreshTokenRepository.findAll().stream()
        .filter(token -> jti.equals(token.getTokenId()))
        .findFirst()
        .orElseThrow(() -> new AssertionError("no stored refresh token with jti " + jti));
  }

  private JsonNode register(String email) throws Exception {
    MvcResult result =
        mockMvc
            .perform(
                post("/api/v1/auth/register")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(
                        String.format(
                            "{\"email\": \"%s\", \"password\": \"password123\","
                                + " \"displayName\": \"Lifecycle User\"}",
                            email)))
            .andExpect(status().isCreated())
            .andReturn();
    return objectMapper.readTree(result.getResponse().getContentAsString());
  }

  private JsonNode login(String email) throws Exception {
    MvcResult result =
        mockMvc
            .perform(
                post("/api/v1/auth/login")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(
                        String.format("{\"email\": \"%s\", \"password\": \"password123\"}", email)))
            .andExpect(status().isOk())
            .andReturn();
    return objectMapper.readTree(result.getResponse().getContentAsString());
  }
}
