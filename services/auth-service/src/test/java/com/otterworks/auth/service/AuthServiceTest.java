package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

import com.otterworks.auth.audit.AuditClient;
import com.otterworks.auth.audit.AuditEvent;
import com.otterworks.auth.dto.AuthResponse;
import com.otterworks.auth.dto.ChangePasswordRequest;
import com.otterworks.auth.dto.LoginRequest;
import com.otterworks.auth.dto.RegisterRequest;
import com.otterworks.auth.entity.RefreshToken;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.security.JwtTokenProvider;
import io.jsonwebtoken.MalformedJwtException;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

@ExtendWith(MockitoExtension.class)
class AuthServiceTest {

  @Mock private UserRepository userRepository;
  @Mock private PasswordEncoder passwordEncoder;
  @Mock private JwtTokenProvider jwtTokenProvider;
  @Mock private RefreshTokenRepository refreshTokenRepository;
  @Mock private AuditClient auditClient;

  @InjectMocks private AuthService authService;

  private User testUser;

  @BeforeEach
  void setUp() {
    testUser = new User();
    testUser.setId(UUID.randomUUID());
    testUser.setEmail("test@otterworks.dev");
    testUser.setDisplayName("Test User");
    testUser.setPasswordHash("$2a$12$encodedpassword");
    testUser.setRoles(Set.of(User.Role.USER));
  }

  @Test
  void register_shouldCreateUserAndReturnTokens() {
    RegisterRequest request = new RegisterRequest();
    request.setEmail("new@otterworks.dev");
    request.setPassword("password123");
    request.setDisplayName("New User");

    when(userRepository.existsByEmail("new@otterworks.dev")).thenReturn(false);
    when(passwordEncoder.encode("password123")).thenReturn("$2a$12$encoded");
    when(userRepository.save(any(User.class)))
        .thenAnswer(
            inv -> {
              User u = inv.getArgument(0);
              u.setId(UUID.randomUUID());
              return u;
            });
    when(jwtTokenProvider.generateAccessToken(any(User.class))).thenReturn("access-token");
    when(jwtTokenProvider.generateRefreshToken(any(User.class))).thenReturn("refresh-token");
    when(jwtTokenProvider.extractJti("refresh-token")).thenReturn("jti-123");
    when(jwtTokenProvider.getAccessTokenExpiry()).thenReturn(3600L);
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(2592000L);
    when(refreshTokenRepository.save(any(RefreshToken.class)))
        .thenAnswer(inv -> inv.getArgument(0));

    AuthResponse response = authService.register(request);

    assertThat(response.getAccessToken()).isEqualTo("access-token");
    assertThat(response.getRefreshToken()).isEqualTo("refresh-token");
    assertThat(response.getTokenType()).isEqualTo("Bearer");
    verify(userRepository).save(any(User.class));
    verify(refreshTokenRepository).save(any(RefreshToken.class));
  }

  @Test
  void register_shouldThrowWhenEmailExists() {
    RegisterRequest request = new RegisterRequest();
    request.setEmail("existing@otterworks.dev");
    request.setPassword("password123");
    request.setDisplayName("Existing User");

    when(userRepository.existsByEmail("existing@otterworks.dev")).thenReturn(true);

    assertThatThrownBy(() -> authService.register(request))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Email already registered");
  }

  @Test
  void login_shouldReturnTokensForValidCredentials() {
    LoginRequest request = new LoginRequest();
    request.setEmail("test@otterworks.dev");
    request.setPassword("password123");

    when(userRepository.findByEmail("test@otterworks.dev")).thenReturn(Optional.of(testUser));
    when(passwordEncoder.matches("password123", testUser.getPasswordHash())).thenReturn(true);
    when(userRepository.save(any(User.class))).thenReturn(testUser);
    when(jwtTokenProvider.generateAccessToken(testUser)).thenReturn("access-token");
    when(jwtTokenProvider.generateRefreshToken(testUser)).thenReturn("refresh-token");
    when(jwtTokenProvider.extractJti("refresh-token")).thenReturn("jti-456");
    when(jwtTokenProvider.getAccessTokenExpiry()).thenReturn(3600L);
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(2592000L);
    when(refreshTokenRepository.save(any(RefreshToken.class)))
        .thenAnswer(inv -> inv.getArgument(0));

    AuthResponse response = authService.login(request);

    assertThat(response.getAccessToken()).isEqualTo("access-token");
    assertThat(response.getUser().getEmail()).isEqualTo("test@otterworks.dev");
  }

  @Test
  void login_shouldThrowForInvalidEmail() {
    LoginRequest request = new LoginRequest();
    request.setEmail("nonexistent@otterworks.dev");
    request.setPassword("password123");

    when(userRepository.findByEmail("nonexistent@otterworks.dev")).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.login(request))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid credentials");
  }

  @Test
  void login_shouldThrowForWrongPassword() {
    LoginRequest request = new LoginRequest();
    request.setEmail("test@otterworks.dev");
    request.setPassword("wrongpassword");

    when(userRepository.findByEmail("test@otterworks.dev")).thenReturn(Optional.of(testUser));
    when(passwordEncoder.matches("wrongpassword", testUser.getPasswordHash())).thenReturn(false);

    assertThatThrownBy(() -> authService.login(request))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid credentials");
  }

  @Test
  void changePassword_shouldUpdatePasswordAndRevokeTokens() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("oldPassword");
    request.setNewPassword("newPassword123");

    when(userRepository.findById(testUser.getId())).thenReturn(Optional.of(testUser));
    when(passwordEncoder.matches("oldPassword", testUser.getPasswordHash())).thenReturn(true);
    when(passwordEncoder.encode("newPassword123")).thenReturn("$2a$12$newencoded");
    when(userRepository.save(any(User.class))).thenReturn(testUser);

    authService.changePassword(testUser.getId(), request);

    verify(userRepository).save(testUser);
    verify(refreshTokenRepository).revokeAllByUserId(testUser.getId());
  }

  @Test
  void changePassword_shouldThrowForWrongCurrentPassword() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("wrongPassword");
    request.setNewPassword("newPassword123");

    when(userRepository.findById(testUser.getId())).thenReturn(Optional.of(testUser));
    when(passwordEncoder.matches("wrongPassword", testUser.getPasswordHash())).thenReturn(false);

    assertThatThrownBy(() -> authService.changePassword(testUser.getId(), request))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Current password is incorrect");
  }

  // --- audit events ---

  private List<AuditEvent> emittedEvents(int expected) {
    ArgumentCaptor<AuditEvent> captor = ArgumentCaptor.forClass(AuditEvent.class);
    verify(auditClient, times(expected)).emit(captor.capture());
    return captor.getAllValues();
  }

  private AuditEvent singleEvent() {
    return emittedEvents(1).get(0);
  }

  private static void assertNoSecrets(List<AuditEvent> events, String... secrets) {
    for (AuditEvent event : events) {
      String rendered = event.toString();
      for (String secret : secrets) {
        assertThat(rendered).doesNotContain(secret);
      }
      assertThat(rendered).doesNotContain("$2a$");
    }
  }

  private void stubTokenIssuance() {
    when(jwtTokenProvider.generateAccessToken(any(User.class))).thenReturn("access-token");
    when(jwtTokenProvider.generateRefreshToken(any(User.class))).thenReturn("refresh-token");
    when(jwtTokenProvider.extractJti("refresh-token")).thenReturn("jti-new");
    when(jwtTokenProvider.getAccessTokenExpiry()).thenReturn(3600L);
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(2592000L);
    when(refreshTokenRepository.save(any(RefreshToken.class)))
        .thenAnswer(inv -> inv.getArgument(0));
  }

  @Test
  void login_success_emitsAuditEventWithoutSecrets() {
    LoginRequest request = new LoginRequest();
    request.setEmail("test@otterworks.dev");
    request.setPassword("password123");
    when(userRepository.findByEmail("test@otterworks.dev")).thenReturn(Optional.of(testUser));
    when(passwordEncoder.matches("password123", testUser.getPasswordHash())).thenReturn(true);
    when(userRepository.save(any(User.class))).thenReturn(testUser);
    stubTokenIssuance();

    authService.login(request);

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.login.success");
    assertThat(event.getOutcome()).isEqualTo("success");
    assertThat(event.getUserId()).isEqualTo(testUser.getId().toString());
    assertThat(event.getActorEmail()).isEqualTo("test@otterworks.dev");
    assertThat(event.getActorType()).isEqualTo("user");
    assertThat(event.getResourceType()).isEqualTo("user");
    assertThat(event.getResourceId()).isEqualTo(testUser.getId().toString());
    assertNoSecrets(List.of(event), "password123", "access-token", "refresh-token");
  }

  @Test
  void login_unknownEmail_emitsFailureWithReasonAndStillChecksAPassword() {
    LoginRequest request = new LoginRequest();
    request.setEmail("ghost@otterworks.dev");
    request.setPassword("password123");
    when(userRepository.findByEmail("ghost@otterworks.dev")).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.login(request))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid credentials");

    // Same amount of hashing work as the wrong-password path (no enumeration timing signal).
    verify(passwordEncoder).matches(eq("password123"), any());
    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.login.failure");
    assertThat(event.getOutcome()).isEqualTo("failure");
    assertThat(event.getUserId()).isEqualTo("anonymous");
    assertThat(event.getActorType()).isEqualTo("anonymous");
    assertThat(event.getResourceType()).isEqualTo("user");
    assertThat(event.getResourceId()).isEqualTo("unknown");
    assertThat(event.getDetails())
        .containsEntry("reason", "unknown_user")
        .containsEntry("attemptedEmail", "ghost@otterworks.dev");
    assertNoSecrets(List.of(event), "password123");
  }

  @Test
  void login_wrongPassword_emitsFailureWithReason() {
    LoginRequest request = new LoginRequest();
    request.setEmail("test@otterworks.dev");
    request.setPassword("wrongpassword");
    when(userRepository.findByEmail("test@otterworks.dev")).thenReturn(Optional.of(testUser));
    when(passwordEncoder.matches("wrongpassword", testUser.getPasswordHash())).thenReturn(false);

    assertThatThrownBy(() -> authService.login(request))
        .isInstanceOf(IllegalArgumentException.class);

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.login.failure");
    assertThat(event.getOutcome()).isEqualTo("failure");
    assertThat(event.getUserId()).isEqualTo("anonymous");
    assertThat(event.getResourceId()).isEqualTo(testUser.getId().toString());
    assertThat(event.getDetails())
        .containsEntry("reason", "bad_password")
        .containsEntry("attemptedEmail", "test@otterworks.dev");
    assertNoSecrets(List.of(event), "wrongpassword");
    verify(userRepository, never()).save(any());
  }

  @Test
  void register_emitsRegisterAndDefaultRolePermissionChange() {
    RegisterRequest request = new RegisterRequest();
    request.setEmail("new@otterworks.dev");
    request.setPassword("password123");
    request.setDisplayName("New User");
    when(userRepository.existsByEmail("new@otterworks.dev")).thenReturn(false);
    when(passwordEncoder.encode("password123")).thenReturn("$2a$12$encoded");
    when(userRepository.save(any(User.class)))
        .thenAnswer(
            inv -> {
              User u = inv.getArgument(0);
              u.setId(UUID.randomUUID());
              return u;
            });
    stubTokenIssuance();

    authService.register(request);

    List<AuditEvent> events = emittedEvents(2);
    AuditEvent register = events.get(0);
    assertThat(register.getAction()).isEqualTo("auth.user.register");
    assertThat(register.getOutcome()).isEqualTo("success");
    assertThat(register.getActorEmail()).isEqualTo("new@otterworks.dev");
    assertThat(register.getResourceType()).isEqualTo("user");
    assertThat(register.getResourceId()).isEqualTo(register.getUserId());

    AuditEvent roles = events.get(1);
    assertThat(roles.getAction()).isEqualTo("permission.change");
    assertThat(roles.getOutcome()).isEqualTo("success");
    assertThat(roles.getResourceId()).isEqualTo(register.getUserId());
    assertThat(roles.getDetails()).containsEntry("before", "").containsEntry("after", "USER");
    assertNoSecrets(events, "password123", "access-token", "refresh-token");
  }

  @Test
  void register_duplicateEmail_emitsNothing() {
    RegisterRequest request = new RegisterRequest();
    request.setEmail("existing@otterworks.dev");
    request.setPassword("password123");
    request.setDisplayName("Existing User");
    when(userRepository.existsByEmail("existing@otterworks.dev")).thenReturn(true);

    assertThatThrownBy(() -> authService.register(request))
        .isInstanceOf(IllegalArgumentException.class);
    verifyNoInteractions(auditClient);
  }

  @Test
  void logout_emitsLogoutEvent() {
    authService.logout(testUser.getId());

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.logout");
    assertThat(event.getOutcome()).isEqualTo("success");
    assertThat(event.getUserId()).isEqualTo(testUser.getId().toString());
    assertThat(event.getResourceType()).isEqualTo("user");
    assertThat(event.getResourceId()).isEqualTo(testUser.getId().toString());
  }

  private RefreshToken storedRefreshToken(Instant expiresAt) {
    RefreshToken stored = new RefreshToken();
    stored.setUser(testUser);
    stored.setTokenId("jti-old");
    stored.setExpiresAt(expiresAt);
    return stored;
  }

  @Test
  void refresh_rotated_emitsRefreshEventWithoutTokens() {
    String userId = testUser.getId().toString();
    when(jwtTokenProvider.extractJti("old-refresh-token")).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("old-refresh-token")).thenReturn(userId);
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.of(storedRefreshToken(Instant.now().plus(1, ChronoUnit.DAYS))));
    when(userRepository.findById(testUser.getId())).thenReturn(Optional.of(testUser));
    stubTokenIssuance();

    authService.refreshToken("old-refresh-token");

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.token.refresh");
    assertThat(event.getOutcome()).isEqualTo("success");
    assertThat(event.getUserId()).isEqualTo(userId);
    assertThat(event.getResourceId()).isEqualTo(userId);
    assertNoSecrets(
        List.of(event), "old-refresh-token", "refresh-token", "access-token", "jti-old");
  }

  @Test
  void refresh_reusedJti_emitsDenied() {
    String userId = testUser.getId().toString();
    when(jwtTokenProvider.extractJti("reused-token")).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("reused-token")).thenReturn(userId);
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("reused-token"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid or revoked refresh token");

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.token.refresh_denied");
    assertThat(event.getOutcome()).isEqualTo("denied");
    assertThat(event.getUserId()).isEqualTo(userId);
    assertThat(event.getDetails()).containsEntry("reason", "revoked_or_reused");
    assertNoSecrets(List.of(event), "reused-token", "jti-old");
  }

  @Test
  void refresh_expired_emitsDenied() {
    String userId = testUser.getId().toString();
    when(jwtTokenProvider.extractJti("expired-token")).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("expired-token")).thenReturn(userId);
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.of(storedRefreshToken(Instant.now().minus(1, ChronoUnit.DAYS))));

    assertThatThrownBy(() -> authService.refreshToken("expired-token"))
        .isInstanceOf(IllegalArgumentException.class);

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.token.refresh_denied");
    assertThat(event.getDetails()).containsEntry("reason", "expired");
  }

  @Test
  void refresh_invalidToken_emitsAnonymousDeniedAndRethrows() {
    when(jwtTokenProvider.extractJti("garbage")).thenThrow(new MalformedJwtException("bad token"));

    assertThatThrownBy(() -> authService.refreshToken("garbage"))
        .isInstanceOf(MalformedJwtException.class);

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.token.refresh_denied");
    assertThat(event.getOutcome()).isEqualTo("denied");
    assertThat(event.getUserId()).isEqualTo("anonymous");
    assertThat(event.getDetails()).containsEntry("reason", "invalid_token");
    assertNoSecrets(List.of(event), "garbage");
  }

  @Test
  void changePassword_success_emitsCredentialChangeWithoutPasswords() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("oldPassword");
    request.setNewPassword("newPassword123");
    when(userRepository.findById(testUser.getId())).thenReturn(Optional.of(testUser));
    when(passwordEncoder.matches("oldPassword", testUser.getPasswordHash())).thenReturn(true);
    when(passwordEncoder.encode("newPassword123")).thenReturn("$2a$12$newencoded");
    when(userRepository.save(any(User.class))).thenReturn(testUser);

    authService.changePassword(testUser.getId(), request);

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.credential.change");
    assertThat(event.getOutcome()).isEqualTo("success");
    assertThat(event.getUserId()).isEqualTo(testUser.getId().toString());
    assertThat(event.getResourceId()).isEqualTo(testUser.getId().toString());
    assertThat(event.getDetails()).containsEntry("credential", "password");
    assertNoSecrets(List.of(event), "oldPassword", "newPassword123", "newencoded");
  }

  @Test
  void changePassword_wrongCurrentPassword_emitsFailure() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("wrongPassword");
    request.setNewPassword("newPassword123");
    when(userRepository.findById(testUser.getId())).thenReturn(Optional.of(testUser));
    when(passwordEncoder.matches("wrongPassword", testUser.getPasswordHash())).thenReturn(false);

    assertThatThrownBy(() -> authService.changePassword(testUser.getId(), request))
        .isInstanceOf(IllegalArgumentException.class);

    AuditEvent event = singleEvent();
    assertThat(event.getAction()).isEqualTo("auth.credential.change");
    assertThat(event.getOutcome()).isEqualTo("failure");
    assertThat(event.getDetails()).containsEntry("reason", "current_password_mismatch");
    assertNoSecrets(List.of(event), "wrongPassword", "newPassword123");
  }
}
