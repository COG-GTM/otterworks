package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
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
  void register_shouldCreateUserWithoutIssuingTokens() {
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

    authService.register(request);

    verify(userRepository)
        .save(
            argThat(
                u ->
                    u.getEmail().equals("new@otterworks.dev")
                        && u.getPasswordHash().equals("$2a$12$encoded")
                        && u.getDisplayName().equals("New User")));
    verifyNoInteractions(jwtTokenProvider, refreshTokenRepository);
  }

  @Test
  void register_shouldSilentlyIgnoreExistingEmail() {
    RegisterRequest request = new RegisterRequest();
    request.setEmail("existing@otterworks.dev");
    request.setPassword("password123");
    request.setDisplayName("Existing User");

    when(userRepository.existsByEmail("existing@otterworks.dev")).thenReturn(true);

    assertThatCode(() -> authService.register(request)).doesNotThrowAnyException();

    verify(passwordEncoder).encode("password123");
    verify(userRepository, never()).save(any(User.class));
    verifyNoInteractions(jwtTokenProvider, refreshTokenRepository);
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
}
