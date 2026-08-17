package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
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
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

@ExtendWith(MockitoExtension.class)
class AuthServiceRefreshAndLogoutTest {

  private static final String OLD_TOKEN = "old-refresh-token";

  @Mock private UserRepository userRepository;
  @Mock private PasswordEncoder passwordEncoder;
  @Mock private JwtTokenProvider jwtTokenProvider;
  @Mock private RefreshTokenRepository refreshTokenRepository;

  @InjectMocks private AuthService authService;

  private User user;
  private UUID userId;

  @BeforeEach
  void setUp() {
    userId = UUID.randomUUID();
    user = new User();
    user.setId(userId);
    user.setEmail("refresh@otterworks.dev");
    user.setDisplayName("Refresh User");
    user.setRoles(Set.of(User.Role.USER));
  }

  private RefreshToken storedToken(Instant expiresAt) {
    RefreshToken token = new RefreshToken();
    token.setUser(user);
    token.setTokenId("jti-old");
    token.setExpiresAt(expiresAt);
    return token;
  }

  @Test
  void refreshToken_rotatesTheStoredTokenAndIssuesNewOnes() {
    RefreshToken stored = storedToken(Instant.now().plus(1, ChronoUnit.DAYS));
    when(jwtTokenProvider.extractJti(OLD_TOKEN)).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId(OLD_TOKEN))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(jwtTokenProvider.generateAccessToken(user)).thenReturn("new-access");
    when(jwtTokenProvider.generateRefreshToken(user)).thenReturn("new-refresh");
    when(jwtTokenProvider.extractJti("new-refresh")).thenReturn("jti-new");
    when(jwtTokenProvider.getAccessTokenExpiry()).thenReturn(3600L);
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(2592000L);
    when(refreshTokenRepository.save(any(RefreshToken.class))).thenAnswer(i -> i.getArgument(0));

    Instant before = Instant.now();
    AuthResponse response = authService.refreshToken(OLD_TOKEN);
    Instant after = Instant.now();

    assertThat(stored.isRevoked()).isTrue();
    assertThat(response.getAccessToken()).isEqualTo("new-access");
    assertThat(response.getRefreshToken()).isEqualTo("new-refresh");
    assertThat(response.getExpiresIn()).isEqualTo(3600L);
    assertThat(response.getUser().getId()).isEqualTo(userId.toString());

    ArgumentCaptor<RefreshToken> saved = ArgumentCaptor.forClass(RefreshToken.class);
    verify(refreshTokenRepository, times(2)).save(saved.capture());
    RefreshToken persisted = saved.getAllValues().get(1);
    assertThat(persisted.getTokenId()).isEqualTo("jti-new");
    assertThat(persisted.getUser()).isSameAs(user);
    assertThat(persisted.getExpiresAt())
        .isBetween(before.plusSeconds(2592000), after.plusSeconds(2592000));
  }

  @Test
  void refreshToken_rejectsUnknownOrRevokedToken() {
    when(jwtTokenProvider.extractJti(OLD_TOKEN)).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId(OLD_TOKEN))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken(OLD_TOKEN))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid or revoked refresh token");
    verify(refreshTokenRepository, never()).save(any());
  }

  @Test
  void refreshToken_rejectsExpiredToken() {
    RefreshToken stored = storedToken(Instant.now().minus(1, ChronoUnit.MINUTES));
    when(jwtTokenProvider.extractJti(OLD_TOKEN)).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId(OLD_TOKEN))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.of(stored));

    assertThatThrownBy(() -> authService.refreshToken(OLD_TOKEN))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token expired");
    assertThat(stored.isRevoked()).isFalse();
    verify(refreshTokenRepository, never()).save(any());
  }

  @Test
  void refreshToken_rejectsTokenOfDeletedUser() {
    RefreshToken stored = storedToken(Instant.now().plus(1, ChronoUnit.DAYS));
    when(jwtTokenProvider.extractJti(OLD_TOKEN)).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId(OLD_TOKEN))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken(OLD_TOKEN))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    assertThat(stored.isRevoked()).isTrue();
  }

  @Test
  void changePassword_rejectsUnknownUser() {
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.changePassword(userId, null))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(refreshTokenRepository, never()).revokeAllByUserId(any());
  }

  @Test
  void logout_revokesEveryRefreshTokenOfTheUser() {
    authService.logout(userId);

    verify(refreshTokenRepository).revokeAllByUserId(userId);
    verify(userRepository, never()).save(any());
  }
}
