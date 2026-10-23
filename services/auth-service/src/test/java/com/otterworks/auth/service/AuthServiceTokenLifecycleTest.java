package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.otterworks.auth.dto.AuthResponse;
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
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

@ExtendWith(MockitoExtension.class)
class AuthServiceTokenLifecycleTest {

  @Mock private UserRepository userRepository;
  @Mock private PasswordEncoder passwordEncoder;
  @Mock private JwtTokenProvider jwtTokenProvider;
  @Mock private RefreshTokenRepository refreshTokenRepository;

  @InjectMocks private AuthService authService;

  private User user;

  @BeforeEach
  void setUp() {
    user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("lifecycle@otterworks.dev");
    user.setDisplayName("Lifecycle User");
    user.setPasswordHash("hash");
    user.setRoles(Set.of(User.Role.USER));
  }

  private void stubTokenIssue() {
    when(jwtTokenProvider.generateAccessToken(any(User.class))).thenReturn("new-access");
    when(jwtTokenProvider.generateRefreshToken(any(User.class))).thenReturn("new-refresh");
    when(jwtTokenProvider.extractJti("new-refresh")).thenReturn("new-jti");
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(2592000L);
    when(jwtTokenProvider.getAccessTokenExpiry()).thenReturn(3600L);
  }

  private RefreshToken storedToken(Instant expiresAt) {
    RefreshToken token = new RefreshToken();
    token.setUser(user);
    token.setTokenId("old-jti");
    token.setExpiresAt(expiresAt);
    return token;
  }

  @Test
  void register_encodesPasswordAndAssignsUserRoleOnly() {
    RegisterRequest request = new RegisterRequest();
    request.setEmail("new@otterworks.dev");
    request.setPassword("password123");
    request.setDisplayName("New");
    when(userRepository.existsByEmail("new@otterworks.dev")).thenReturn(false);
    when(passwordEncoder.encode("password123")).thenReturn("bcrypt-hash");
    when(userRepository.save(any(User.class)))
        .thenAnswer(
            inv -> {
              User u = inv.getArgument(0);
              u.setId(UUID.randomUUID());
              return u;
            });
    stubTokenIssue();

    authService.register(request);

    ArgumentCaptor<User> captor = ArgumentCaptor.forClass(User.class);
    verify(userRepository).save(captor.capture());
    assertThat(captor.getValue().getPasswordHash()).isEqualTo("bcrypt-hash");
    assertThat(captor.getValue().getPasswordHash()).isNotEqualTo("password123");
    assertThat(captor.getValue().getRoles()).containsExactly(User.Role.USER);
  }

  @Test
  void issuedRefreshTokenIsPersistedWithExpiry() {
    LoginRequest request = new LoginRequest();
    request.setEmail(user.getEmail());
    request.setPassword("pw");
    when(userRepository.findByEmail(user.getEmail())).thenReturn(Optional.of(user));
    when(passwordEncoder.matches("pw", "hash")).thenReturn(true);
    stubTokenIssue();
    Instant before = Instant.now();

    AuthResponse response = authService.login(request);

    ArgumentCaptor<RefreshToken> captor = ArgumentCaptor.forClass(RefreshToken.class);
    verify(refreshTokenRepository).save(captor.capture());
    RefreshToken saved = captor.getValue();
    assertThat(saved.getTokenId()).isEqualTo("new-jti");
    assertThat(saved.getUser()).isSameAs(user);
    assertThat(saved.isRevoked()).isFalse();
    assertThat(saved.getExpiresAt()).isAfter(before.plusSeconds(2592000 - 5));
    assertThat(response.getExpiresIn()).isEqualTo(3600L);
    assertThat(response.getTokenType()).isEqualTo("Bearer");
  }

  @Test
  void login_setsLastLoginAt() {
    LoginRequest request = new LoginRequest();
    request.setEmail(user.getEmail());
    request.setPassword("pw");
    when(userRepository.findByEmail(user.getEmail())).thenReturn(Optional.of(user));
    when(passwordEncoder.matches("pw", "hash")).thenReturn(true);
    stubTokenIssue();

    authService.login(request);

    assertThat(user.getLastLoginAt()).isNotNull();
  }

  @Test
  void login_unknownEmailAndWrongPasswordShareTheSameMessage() {
    LoginRequest unknown = new LoginRequest();
    unknown.setEmail("ghost@otterworks.dev");
    unknown.setPassword("pw");
    when(userRepository.findByEmail("ghost@otterworks.dev")).thenReturn(Optional.empty());
    LoginRequest wrong = new LoginRequest();
    wrong.setEmail(user.getEmail());
    wrong.setPassword("bad");
    when(userRepository.findByEmail(user.getEmail())).thenReturn(Optional.of(user));
    when(passwordEncoder.matches("bad", "hash")).thenReturn(false);

    String unknownMsg =
        catchThrowableOfType(() -> authService.login(unknown), IllegalArgumentException.class)
            .getMessage();
    String wrongMsg =
        catchThrowableOfType(() -> authService.login(wrong), IllegalArgumentException.class)
            .getMessage();

    assertThat(unknownMsg).isEqualTo(wrongMsg).isEqualTo("Invalid credentials");
    verify(refreshTokenRepository, never()).save(any());
  }

  @Test
  void refresh_rotatesTokenAndRevokesOld() {
    RefreshToken stored = storedToken(Instant.now().plusSeconds(600));
    when(jwtTokenProvider.extractJti("old-refresh")).thenReturn("old-jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("old-refresh"))
        .thenReturn(user.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("old-jti"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(user.getId())).thenReturn(Optional.of(user));
    stubTokenIssue();

    AuthResponse response = authService.refreshToken("old-refresh");

    assertThat(stored.isRevoked()).isTrue();
    assertThat(response.getAccessToken()).isEqualTo("new-access");
    assertThat(response.getRefreshToken()).isEqualTo("new-refresh");
    verify(refreshTokenRepository, times(2)).save(any(RefreshToken.class));
  }

  @Test
  void refresh_revokedOrUnknownTokenRejected() {
    when(jwtTokenProvider.extractJti("old-refresh")).thenReturn("old-jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("old-refresh"))
        .thenReturn(user.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("old-jti"))
        .thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("old-refresh"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("revoked");
    verify(jwtTokenProvider, never()).generateAccessToken(any());
  }

  @Test
  void refresh_storedTokenPastExpiryRejected() {
    RefreshToken stored = storedToken(Instant.now().minusSeconds(1));
    when(jwtTokenProvider.extractJti("old-refresh")).thenReturn("old-jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("old-refresh"))
        .thenReturn(user.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("old-jti"))
        .thenReturn(Optional.of(stored));

    assertThatThrownBy(() -> authService.refreshToken("old-refresh"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token expired");
    assertThat(stored.isRevoked()).isFalse();
  }

  @Test
  void refresh_accessTokenRejected() {
    when(jwtTokenProvider.extractJti("access")).thenReturn(null);
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("access"))
        .thenThrow(new IllegalArgumentException("Token is not a refresh token"));

    assertThatThrownBy(() -> authService.refreshToken("access"))
        .isInstanceOf(IllegalArgumentException.class);
    verify(refreshTokenRepository, never()).findByTokenIdAndRevokedFalse(any());
  }

  @Test
  void refresh_deletedUserRejected() {
    RefreshToken stored = storedToken(Instant.now().plusSeconds(600));
    when(jwtTokenProvider.extractJti("old-refresh")).thenReturn("old-jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("old-refresh"))
        .thenReturn(user.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("old-jti"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(user.getId())).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("old-refresh"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
  }

  @Test
  void logout_revokesAllRefreshTokens() {
    authService.logout(user.getId());

    verify(refreshTokenRepository).revokeAllByUserId(user.getId());
  }
}
