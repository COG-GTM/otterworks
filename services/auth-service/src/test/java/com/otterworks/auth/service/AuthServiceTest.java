package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.otterworks.auth.dto.AuthResponse;
import com.otterworks.auth.dto.ChangePasswordRequest;
import com.otterworks.auth.dto.LoginRequest;
import com.otterworks.auth.dto.RegisterRequest;
import com.otterworks.auth.entity.RefreshToken;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.security.JwtTokenProvider;
import java.time.Instant;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
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

  private RefreshToken storedToken(Instant expiresAt) {
    RefreshToken token = new RefreshToken();
    token.setUser(testUser);
    token.setTokenId("jti-1");
    token.setExpiresAt(expiresAt);
    return token;
  }

  @Test
  void refreshToken_shouldRevokeOldTokenAndIssueNewPair() {
    RefreshToken stored = storedToken(Instant.now().plusSeconds(600));
    when(jwtTokenProvider.extractJti("old")).thenReturn("jti-1", "jti-2");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("old"))
        .thenReturn(testUser.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-1"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(testUser.getId())).thenReturn(Optional.of(testUser));
    when(jwtTokenProvider.generateAccessToken(testUser)).thenReturn("access");
    when(jwtTokenProvider.generateRefreshToken(testUser)).thenReturn("old");
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(60L);

    AuthResponse response = authService.refreshToken("old");

    assertThat(stored.isRevoked()).isTrue();
    assertThat(response.getAccessToken()).isEqualTo("access");
    verify(refreshTokenRepository).save(stored);
    verify(refreshTokenRepository, times(2)).save(any(RefreshToken.class));
  }

  @Test
  void refreshToken_shouldRejectRevokedOrUnknownToken() {
    when(jwtTokenProvider.extractJti("tok")).thenReturn("jti-1");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("tok"))
        .thenReturn(testUser.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-1")).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("tok"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid or revoked refresh token");
  }

  @Test
  void refreshToken_shouldRejectExpiredStoredToken() {
    RefreshToken stored = storedToken(Instant.now().minusSeconds(1));
    when(jwtTokenProvider.extractJti("tok")).thenReturn("jti-1");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("tok"))
        .thenReturn(testUser.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-1"))
        .thenReturn(Optional.of(stored));

    assertThatThrownBy(() -> authService.refreshToken("tok"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token expired");
    assertThat(stored.isRevoked()).isFalse();
    verify(refreshTokenRepository, never()).save(any());
  }

  @Test
  void refreshToken_shouldRejectWhenUserNoLongerExists() {
    RefreshToken stored = storedToken(Instant.now().plusSeconds(600));
    when(jwtTokenProvider.extractJti("tok")).thenReturn("jti-1");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("tok"))
        .thenReturn(testUser.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-1"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(testUser.getId())).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("tok"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
  }

  @Test
  void changePassword_shouldThrowWhenUserMissing() {
    UUID id = UUID.randomUUID();
    when(userRepository.findById(id)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.changePassword(id, new ChangePasswordRequest()))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(refreshTokenRepository, never()).revokeAllByUserId(any());
  }

  @Test
  void logout_shouldRevokeAllRefreshTokens() {
    authService.logout(testUser.getId());

    verify(refreshTokenRepository).revokeAllByUserId(testUser.getId());
  }
}
