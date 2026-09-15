package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.otterworks.auth.dto.AuthResponse;
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
import org.mockito.Captor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

/** Rotation and revocation behaviour of the refresh-token half of the auth flow. */
@ExtendWith(MockitoExtension.class)
class AuthServiceRefreshTokenTest {

  @Mock private UserRepository userRepository;
  @Mock private PasswordEncoder passwordEncoder;
  @Mock private JwtTokenProvider jwtTokenProvider;
  @Mock private RefreshTokenRepository refreshTokenRepository;

  @Captor private ArgumentCaptor<RefreshToken> refreshTokenCaptor;

  @InjectMocks private AuthService authService;

  private User testUser;
  private RefreshToken storedToken;

  @BeforeEach
  void setUp() {
    testUser = new User();
    testUser.setId(UUID.randomUUID());
    testUser.setEmail("rotate@otterworks.dev");
    testUser.setDisplayName("Rotate User");
    testUser.setPasswordHash("$2a$12$encodedpassword");
    testUser.setRoles(Set.of(User.Role.USER));

    storedToken = new RefreshToken();
    storedToken.setUser(testUser);
    storedToken.setTokenId("old-jti");
    storedToken.setExpiresAt(Instant.now().plus(30, ChronoUnit.DAYS));
  }

  @Test
  void refreshToken_shouldRevokeThePresentedTokenAndIssueANewPair() {
    stubRefreshLookup();
    when(userRepository.findById(testUser.getId())).thenReturn(Optional.of(testUser));
    when(jwtTokenProvider.generateAccessToken(testUser)).thenReturn("new-access-token");
    when(jwtTokenProvider.generateRefreshToken(testUser)).thenReturn("new-refresh-token");
    when(jwtTokenProvider.extractJti("new-refresh-token")).thenReturn("new-jti");
    when(jwtTokenProvider.getAccessTokenExpiry()).thenReturn(3600L);
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(2592000L);
    when(refreshTokenRepository.save(any(RefreshToken.class))).thenAnswer(inv -> inv.getArgument(0));

    AuthResponse response = authService.refreshToken("old-refresh-token");

    assertThat(response.getAccessToken()).isEqualTo("new-access-token");
    assertThat(response.getRefreshToken()).isEqualTo("new-refresh-token");
    assertThat(response.getUser().getEmail()).isEqualTo("rotate@otterworks.dev");

    verify(refreshTokenRepository, times(2)).save(refreshTokenCaptor.capture());
    List<RefreshToken> saved = refreshTokenCaptor.getAllValues();
    assertThat(saved.get(0).getTokenId()).isEqualTo("old-jti");
    assertThat(saved.get(0).isRevoked()).as("presented token is rotated out").isTrue();
    assertThat(saved.get(1).getTokenId()).isEqualTo("new-jti");
    assertThat(saved.get(1).isRevoked()).isFalse();
    assertThat(saved.get(1).getExpiresAt()).isAfter(Instant.now());
  }

  @Test
  void refreshToken_shouldRejectRevokedOrUnknownToken() {
    when(jwtTokenProvider.extractJti("old-refresh-token")).thenReturn("old-jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("old-refresh-token"))
        .thenReturn(testUser.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("old-jti"))
        .thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("old-refresh-token"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid or revoked refresh token");

    verify(refreshTokenRepository, never()).save(any(RefreshToken.class));
  }

  @Test
  void refreshToken_shouldRejectExpiredStoredToken() {
    storedToken.setExpiresAt(Instant.now().minus(1, ChronoUnit.MINUTES));
    stubRefreshLookup();

    assertThatThrownBy(() -> authService.refreshToken("old-refresh-token"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token expired");

    verify(userRepository, never()).findById(any(UUID.class));
  }

  @Test
  void refreshToken_shouldRejectTokenWhoseUserNoLongerExists() {
    stubRefreshLookup();
    when(refreshTokenRepository.save(any(RefreshToken.class))).thenAnswer(inv -> inv.getArgument(0));
    when(userRepository.findById(testUser.getId())).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("old-refresh-token"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");

    verify(jwtTokenProvider, never()).generateAccessToken(any(User.class));
  }

  @Test
  void refreshToken_shouldRejectAnAccessTokenPresentedAsRefreshToken() {
    when(jwtTokenProvider.extractJti("access-token")).thenReturn("jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("access-token"))
        .thenThrow(new IllegalArgumentException("Token is not a refresh token"));

    assertThatThrownBy(() -> authService.refreshToken("access-token"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Token is not a refresh token");

    verify(refreshTokenRepository, never()).save(any(RefreshToken.class));
  }

  @Test
  void logout_shouldRevokeEveryRefreshTokenOfTheUser() {
    authService.logout(testUser.getId());

    verify(refreshTokenRepository).revokeAllByUserId(testUser.getId());
    verify(refreshTokenRepository, never()).save(any(RefreshToken.class));
  }

  private void stubRefreshLookup() {
    when(jwtTokenProvider.extractJti("old-refresh-token")).thenReturn("old-jti");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("old-refresh-token"))
        .thenReturn(testUser.getId().toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("old-jti"))
        .thenReturn(Optional.of(storedToken));
  }
}
