package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.otterworks.auth.dto.AuthResponse;
import com.otterworks.auth.entity.RefreshToken;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.security.JwtTokenProvider;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
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
class AuthServiceRefreshTokenTest {

  private static final String PRESENTED_TOKEN = "presented-refresh-token";
  private static final String PRESENTED_JTI = "jti-presented";

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
    user.setEmail("refresh@otterworks.dev");
    user.setDisplayName("Refresh User");
    user.setRoles(Set.of(User.Role.USER));
  }

  @Test
  void refreshToken_shouldRotateTheStoredTokenAndIssueNewOnes() {
    RefreshToken stored = storedToken(Instant.now().plus(1, ChronoUnit.DAYS));
    when(jwtTokenProvider.extractJti(PRESENTED_TOKEN)).thenReturn(PRESENTED_JTI);
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId(PRESENTED_TOKEN))
        .thenReturn(user.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse(PRESENTED_JTI))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(user.getId())).thenReturn(Optional.of(user));
    when(jwtTokenProvider.generateAccessToken(user)).thenReturn("new-access-token");
    when(jwtTokenProvider.generateRefreshToken(user)).thenReturn("new-refresh-token");
    when(jwtTokenProvider.extractJti("new-refresh-token")).thenReturn("jti-new");
    when(jwtTokenProvider.getAccessTokenExpiry()).thenReturn(3600L);
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(2592000L);
    when(refreshTokenRepository.save(any(RefreshToken.class))).thenAnswer(i -> i.getArgument(0));

    AuthResponse response = authService.refreshToken(PRESENTED_TOKEN);

    assertThat(response.getAccessToken()).isEqualTo("new-access-token");
    assertThat(response.getRefreshToken()).isEqualTo("new-refresh-token");
    assertThat(response.getExpiresIn()).isEqualTo(3600L);
    assertThat(response.getUser().getEmail()).isEqualTo("refresh@otterworks.dev");
    assertThat(stored.isRevoked()).isTrue();
  }

  @Test
  void refreshToken_shouldRejectRevokedOrUnknownToken() {
    when(jwtTokenProvider.extractJti(PRESENTED_TOKEN)).thenReturn(PRESENTED_JTI);
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId(PRESENTED_TOKEN))
        .thenReturn(user.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse(PRESENTED_JTI))
        .thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken(PRESENTED_TOKEN))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid or revoked refresh token");
    verify(refreshTokenRepository, never()).save(any());
  }

  @Test
  void refreshToken_shouldRejectExpiredToken() {
    RefreshToken stored = storedToken(Instant.now().minus(1, ChronoUnit.MINUTES));
    when(jwtTokenProvider.extractJti(PRESENTED_TOKEN)).thenReturn(PRESENTED_JTI);
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId(PRESENTED_TOKEN))
        .thenReturn(user.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse(PRESENTED_JTI))
        .thenReturn(Optional.of(stored));

    assertThatThrownBy(() -> authService.refreshToken(PRESENTED_TOKEN))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token expired");
    assertThat(stored.isRevoked()).isFalse();
    verify(refreshTokenRepository, never()).save(any());
  }

  @Test
  void refreshToken_shouldRejectTokenForDeletedUser() {
    RefreshToken stored = storedToken(Instant.now().plus(1, ChronoUnit.DAYS));
    when(jwtTokenProvider.extractJti(PRESENTED_TOKEN)).thenReturn(PRESENTED_JTI);
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId(PRESENTED_TOKEN))
        .thenReturn(user.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse(PRESENTED_JTI))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(user.getId())).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken(PRESENTED_TOKEN))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
  }

  @Test
  void changePassword_shouldRejectUnknownUser() {
    UUID unknown = UUID.randomUUID();
    when(userRepository.findById(unknown)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.changePassword(unknown, null))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(refreshTokenRepository, never()).revokeAllByUserId(any());
  }

  @Test
  void logout_shouldRevokeEveryRefreshTokenOfTheUser() {
    authService.logout(user.getId());

    verify(refreshTokenRepository).revokeAllByUserId(user.getId());
  }

  private RefreshToken storedToken(Instant expiresAt) {
    RefreshToken token = new RefreshToken();
    token.setUser(user);
    token.setTokenId(PRESENTED_JTI);
    token.setExpiresAt(expiresAt);
    return token;
  }
}
