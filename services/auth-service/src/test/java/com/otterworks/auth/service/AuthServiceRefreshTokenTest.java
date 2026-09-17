package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.otterworks.auth.dto.AuthResponse;
import com.otterworks.auth.dto.ChangePasswordRequest;
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
    userId = UUID.randomUUID();
    user = new User();
    user.setId(userId);
    user.setEmail("user@otterworks.dev");
    user.setDisplayName("User One");
    user.setAvatarUrl("https://cdn/avatar.png");
    user.setPasswordHash("$2a$12$hash");
    user.setRoles(Set.of(User.Role.USER));
  }

  private RefreshToken storedToken(Instant expiresAt) {
    RefreshToken token = new RefreshToken();
    token.setTokenId("jti-old");
    token.setUser(user);
    token.setExpiresAt(expiresAt);
    return token;
  }

  @Test
  void refreshToken_rotatesTheStoredTokenAndIssuesANewPair() {
    RefreshToken stored = storedToken(Instant.now().plus(1, ChronoUnit.DAYS));
    when(jwtTokenProvider.extractJti("refresh-old")).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("refresh-old"))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(jwtTokenProvider.generateAccessToken(user)).thenReturn("access-new");
    when(jwtTokenProvider.generateRefreshToken(user)).thenReturn("refresh-new");
    when(jwtTokenProvider.extractJti("refresh-new")).thenReturn("jti-new");
    when(jwtTokenProvider.getAccessTokenExpiry()).thenReturn(3600L);
    when(jwtTokenProvider.getRefreshTokenExpiry()).thenReturn(2592000L);
    when(refreshTokenRepository.save(any(RefreshToken.class))).thenAnswer(i -> i.getArgument(0));

    AuthResponse response = authService.refreshToken("refresh-old");

    assertThat(response.getAccessToken()).isEqualTo("access-new");
    assertThat(response.getRefreshToken()).isEqualTo("refresh-new");
    assertThat(response.getTokenType()).isEqualTo("Bearer");
    assertThat(response.getExpiresIn()).isEqualTo(3600L);
    assertThat(response.getUser().getId()).isEqualTo(userId.toString());
    assertThat(response.getUser().getAvatarUrl()).isEqualTo("https://cdn/avatar.png");
    assertThat(stored.isRevoked()).as("the presented token must be single-use").isTrue();

    ArgumentCaptor<RefreshToken> saved = ArgumentCaptor.forClass(RefreshToken.class);
    verify(refreshTokenRepository, org.mockito.Mockito.times(2)).save(saved.capture());
    RefreshToken issued = saved.getAllValues().get(1);
    assertThat(issued.getTokenId()).isEqualTo("jti-new");
    assertThat(issued.getUser()).isSameAs(user);
    assertThat(issued.getExpiresAt()).isAfter(Instant.now().plus(29, ChronoUnit.DAYS));
  }

  @Test
  void refreshToken_rejectsATokenThatIsUnknownOrAlreadyRevoked() {
    when(jwtTokenProvider.extractJti("refresh-old")).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("refresh-old"))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("refresh-old"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Invalid or revoked refresh token");
    verify(refreshTokenRepository, never()).save(any());
    verifyNoInteractions(userRepository);
  }

  @Test
  void refreshToken_rejectsAnExpiredStoredToken() {
    RefreshToken stored = storedToken(Instant.now().minus(1, ChronoUnit.SECONDS));
    when(jwtTokenProvider.extractJti("refresh-old")).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("refresh-old"))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.of(stored));

    assertThatThrownBy(() -> authService.refreshToken("refresh-old"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Refresh token expired");
    assertThat(stored.isRevoked()).isFalse();
    verify(refreshTokenRepository, never()).save(any());
  }

  @Test
  void refreshToken_rejectsATokenWhoseUserNoLongerExists() {
    RefreshToken stored = storedToken(Instant.now().plus(1, ChronoUnit.DAYS));
    when(jwtTokenProvider.extractJti("refresh-old")).thenReturn("jti-old");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("refresh-old"))
        .thenReturn(userId.toString());
    when(refreshTokenRepository.findByTokenIdAndRevokedFalse("jti-old"))
        .thenReturn(Optional.of(stored));
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.refreshToken("refresh-old"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    assertThat(stored.isRevoked()).as("the presented token is burned even on failure").isTrue();
  }

  @Test
  void refreshToken_propagatesRejectionOfANonRefreshToken() {
    when(jwtTokenProvider.extractJti("access-token")).thenReturn("jti-access");
    when(jwtTokenProvider.validateRefreshTokenAndGetUserId("access-token"))
        .thenThrow(new IllegalArgumentException("Token is not a refresh token"));

    assertThatThrownBy(() -> authService.refreshToken("access-token"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("Token is not a refresh token");
    verifyNoInteractions(refreshTokenRepository);
  }

  @Test
  void logout_revokesEveryRefreshTokenOfTheUser() {
    authService.logout(userId);

    verify(refreshTokenRepository).revokeAllByUserId(userId);
    verifyNoInteractions(userRepository, jwtTokenProvider, passwordEncoder);
  }

  @Test
  void changePassword_rejectsAnUnknownUser() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("old");
    request.setNewPassword("newPassword123");
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> authService.changePassword(userId, request))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(refreshTokenRepository, never()).revokeAllByUserId(any());
  }
}
