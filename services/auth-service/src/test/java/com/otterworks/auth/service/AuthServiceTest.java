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

  private RefreshToken storedRefreshToken(String jti, Instant expiresAt) {
    RefreshToken token = new RefreshToken();
    token.setUser(testUser);
    token.setTokenId(jti);
    token.setExpiresAt(expiresAt);
    return token;
  }

  @Test
  void refreshToken_shouldRevokeUsedTokenAndIssueNewPair() {
    RefreshToken stored = storedRefreshToken("old-jti", Instant.now().plus(1, ChronoUnit.DAYS));
    when(jwtTokenProvider.extractJti("old-refresh")).thenReturn("old-jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("old-refresh"))
        .thenReturn(testUser.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("old-jti"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(testUser.getId())).thenReturn(Optional.of(testUser));
    when(jwtTokenProvider.generateAccessToken(testUser)).thenReturn("new-access");
    when(jwtTokenProvider.generateRefreshToken(testUser)).thenReturn("new-refresh");
    when(jwtTokenProvider.extractJti("new-refresh")).thenReturn("new-jti");
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(2592000L);
    when(jwtTokenProvider.getAccessTokenExpiry()).thenReturn(3600L);

    AuthResponse response = authService.refreshToken("old-refresh");

    assertThat(response.getAccessToken()).isEqualTo("new-access");
    assertThat(response.getRefreshToken()).isEqualTo("new-refresh");
    assertThat(stored.isRevoked()).isTrue();

    ArgumentCaptor<RefreshToken> saved = ArgumentCaptor.forClass(RefreshToken.class);
    verify(refreshTokenRepository, times(2)).save(saved.capture());
    List<RefreshToken> savedTokens = saved.getAllValues();
    assertThat(savedTokens.get(0)).isSameAs(stored);
    RefreshToken issued = savedTokens.get(1);
    assertThat(issued.getTokenId()).isEqualTo("new-jti");
    assertThat(issued.getUser()).isSameAs(testUser);
    assertThat(issued.isRevoked()).isFalse();
    assertThat(issued.getExpiresAt()).isAfter(Instant.now().plus(29, ChronoUnit.DAYS));
  }

  @Test
  void refreshToken_shouldRejectRevokedOrUnknownToken() {
    when(jwtTokenProvider.extractJti("reused-refresh")).thenReturn("revoked-jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("reused-refresh"))
        .thenReturn(testUser.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("revoked-jti"))
        .thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("reused-refresh"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid or revoked refresh token");

    verify(refreshTokenRepository, never()).save(any());
    verify(jwtTokenProvider, never()).generateAccessToken(any());
  }

  @Test
  void refreshToken_shouldRejectExpiredStoredToken() {
    RefreshToken stored =
        storedRefreshToken("expired-jti", Instant.now().minus(1, ChronoUnit.MINUTES));
    when(jwtTokenProvider.extractJti("expired-refresh")).thenReturn("expired-jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("expired-refresh"))
        .thenReturn(testUser.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("expired-jti"))
        .thenReturn(Optional.of(stored));

    assertThatThrownBy(() -> authService.refreshToken("expired-refresh"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token expired");

    verify(refreshTokenRepository, never()).save(any());
    verify(jwtTokenProvider, never()).generateAccessToken(any());
  }

  @Test
  void refreshToken_shouldRejectAccessToken() {
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("access-token"))
        .thenThrow(new IllegalArgumentException("Token is not a refresh token"));

    assertThatThrownBy(() -> authService.refreshToken("access-token"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Token is not a refresh token");

    verify(refreshTokenRepository, never()).findByTokenIdAndRevokedFalse(any());
    verify(jwtTokenProvider, never()).generateAccessToken(any());
  }

  @Test
  void refreshToken_shouldRejectWhenUserNoLongerExists() {
    RefreshToken stored = storedRefreshToken("jti", Instant.now().plus(1, ChronoUnit.DAYS));
    when(jwtTokenProvider.extractJti("orphan-refresh")).thenReturn("jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("orphan-refresh"))
        .thenReturn(testUser.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(testUser.getId())).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("orphan-refresh"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");

    verify(jwtTokenProvider, never()).generateAccessToken(any());
  }

  @Test
  void logout_shouldRevokeAllRefreshTokensForUser() {
    authService.logout(testUser.getId());

    verify(refreshTokenRepository).revokeAllByUserId(testUser.getId());
  }

  @Test
  void changePassword_shouldNotRevokeTokensWhenCurrentPasswordWrong() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("wrongPassword");
    request.setNewPassword("newPassword123");

    when(userRepository.findById(testUser.getId())).thenReturn(Optional.of(testUser));
    when(passwordEncoder.matches("wrongPassword", testUser.getPasswordHash())).thenReturn(false);

    assertThatThrownBy(() -> authService.changePassword(testUser.getId(), request))
        .isInstanceOf(IllegalArgumentException.class);

    verify(userRepository, never()).save(any());
    verify(refreshTokenRepository, never()).revokeAllByUserId(any());
  }
}
