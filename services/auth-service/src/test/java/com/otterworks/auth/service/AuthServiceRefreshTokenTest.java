package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
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

/** Covers the refresh-token rotation and logout paths of {@link AuthService}. */
@ExtendWith(MockitoExtension.class)
class AuthServiceRefreshTokenTest {

  @Mock private UserRepository userRepository;
  @Mock private PasswordEncoder passwordEncoder;
  @Mock private JwtTokenProvider jwtTokenProvider;
  @Mock private RefreshTokenRepository refreshTokenRepository;

  @InjectMocks private AuthService authService;

  private User user;
  private UUID userId;

  @BeforeEach
  void setUp() {
    userId = UUID.fromString("99999999-8888-7777-6666-555555555555");
    user = new User();
    user.setId(userId);
    user.setEmail("rotate@otterworks.dev");
    user.setDisplayName("Rotate User");
    user.setRoles(Set.of(User.Role.USER));
  }

  @Test
  void refreshToken_shouldRevokeOldTokenAndIssueNewPair() {
    RefreshToken stored = new RefreshToken();
    stored.setTokenId("jti-old");
    stored.setUser(user);
    stored.setExpiresAt(Instant.now().plus(1, ChronoUnit.DAYS));

    when(jwtTokenProvider.extractJti("old-refresh")).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("old-refresh"))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(jwtTokenProvider.generateAccessToken(user)).thenReturn("new-access");
    when(jwtTokenProvider.generateRefreshToken(user)).thenReturn("new-refresh");
    when(jwtTokenProvider.extractJti("new-refresh")).thenReturn("jti-new");
    when(jwtTokenProvider.getAccessTokenExpiry()).thenReturn(3600L);
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(2592000L);
    when(refreshTokenRepository.save(any(RefreshToken.class)))
        .thenAnswer(inv -> inv.getArgument(0));

    AuthResponse response = authService.refreshToken("old-refresh");

    assertThat(stored.isRevoked()).isTrue();
    assertThat(response.getAccessToken()).isEqualTo("new-access");
    assertThat(response.getRefreshToken()).isEqualTo("new-refresh");
    assertThat(response.getUser().getId()).isEqualTo(userId.toString());
    verify(refreshTokenRepository).save(stored);
  }

  @Test
  void refreshToken_shouldRejectRevokedOrUnknownToken() {
    when(jwtTokenProvider.extractJti("unknown")).thenReturn("jti-unknown");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("unknown"))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-unknown"))
        .thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("unknown"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid or revoked refresh token");
    verify(refreshTokenRepository, never()).save(any(RefreshToken.class));
    verifyNoInteractions(userRepository);
  }

  @Test
  void refreshToken_shouldRejectExpiredToken() {
    RefreshToken expired = new RefreshToken();
    expired.setTokenId("jti-expired");
    expired.setUser(user);
    expired.setExpiresAt(Instant.now().minus(1, ChronoUnit.SECONDS));

    when(jwtTokenProvider.extractJti("expired")).thenReturn("jti-expired");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("expired"))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-expired"))
        .thenReturn(Optional.of(expired));

    assertThatThrownBy(() -> authService.refreshToken("expired"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token expired");
    assertThat(expired.isRevoked()).isFalse();
    verify(refreshTokenRepository, never()).save(any(RefreshToken.class));
  }

  @Test
  void refreshToken_shouldRejectTokenOfDeletedUser() {
    RefreshToken stored = new RefreshToken();
    stored.setTokenId("jti-orphan");
    stored.setExpiresAt(Instant.now().plus(1, ChronoUnit.DAYS));

    when(jwtTokenProvider.extractJti("orphan")).thenReturn("jti-orphan");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("orphan")).thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-orphan"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("orphan"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
  }

  @Test
  void refreshToken_shouldPropagateProviderValidationFailure() {
    when(jwtTokenProvider.extractJti("access-token")).thenReturn("jti-access");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("access-token"))
        .thenThrow(new IllegalArgumentException("Token is not a refresh token"));

    assertThatThrownBy(() -> authService.refreshToken("access-token"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Token is not a refresh token");
    verifyNoInteractions(refreshTokenRepository);
  }

  @Test
  void changePassword_shouldRejectUnknownUser() {
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.changePassword(userId, null))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verifyNoInteractions(passwordEncoder);
  }

  @Test
  void logout_shouldRevokeEveryRefreshTokenOfTheUser() {
    authService.logout(userId);

    verify(refreshTokenRepository).revokeAllByUserId(userId);
    verifyNoInteractions(userRepository, jwtTokenProvider, passwordEncoder);
  }
}
