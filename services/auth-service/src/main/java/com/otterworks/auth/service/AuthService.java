package com.otterworks.auth.service;

import com.otterworks.auth.dto.AuthResponse;
import com.otterworks.auth.dto.ChangePasswordRequest;
import com.otterworks.auth.dto.LoginRequest;
import com.otterworks.auth.dto.RegisterRequest;
import com.otterworks.auth.entity.RefreshToken;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.exception.RegistrationRejectedException;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.security.JwtTokenProvider;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Set;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {

  private static final Logger log = LoggerFactory.getLogger(AuthService.class);

  private final UserRepository userRepository;
  private final PasswordEncoder passwordEncoder;
  private final JwtTokenProvider jwtTokenProvider;
  private final RefreshTokenRepository refreshTokenRepository;

  public AuthService(
      UserRepository userRepository,
      PasswordEncoder passwordEncoder,
      JwtTokenProvider jwtTokenProvider,
      RefreshTokenRepository refreshTokenRepository) {
    this.userRepository = userRepository;
    this.passwordEncoder = passwordEncoder;
    this.jwtTokenProvider = jwtTokenProvider;
    this.refreshTokenRepository = refreshTokenRepository;
  }

  @Transactional
  public AuthResponse register(RegisterRequest request) {
    // Hash before the existence check so both outcomes pay the same bcrypt cost.
    String passwordHash = passwordEncoder.encode(request.getPassword());
    if (userRepository.existsByEmail(request.getEmail())) {
      log.info("Registration rejected");
      throw new RegistrationRejectedException();
    }

    User user = new User();
    user.setEmail(request.getEmail());
    user.setPasswordHash(passwordHash);
    user.setDisplayName(request.getDisplayName());
    user.setRoles(Set.of(User.Role.USER));
    try {
      user = userRepository.saveAndFlush(user);
    } catch (DataIntegrityViolationException e) {
      log.info("Registration rejected");
      throw new RegistrationRejectedException();
    }

    log.info("User registered: email={}", user.getEmail());
    return buildAuthResponse(user);
  }

  @Transactional
  public AuthResponse login(LoginRequest request) {
    User user =
        userRepository
            .findByEmail(request.getEmail())
            .orElseThrow(() -> new IllegalArgumentException("Invalid credentials"));

    if (!passwordEncoder.matches(request.getPassword(), user.getPasswordHash())) {
      throw new IllegalArgumentException("Invalid credentials");
    }

    user.setLastLoginAt(Instant.now());
    userRepository.save(user);

    log.info("User logged in: email={}", user.getEmail());
    return buildAuthResponse(user);
  }

  @Transactional
  public AuthResponse refreshToken(String token) {
    String jti = jwtTokenProvider.extractJti(token);
    String userId = jwtTokenProvider.validateRefreshTokenAndGetUserId(token);

    RefreshToken storedToken =
        refreshTokenRepository
            .findByTokenIdAndRevokedFalse(jti)
            .orElseThrow(() -> new IllegalArgumentException("Invalid or revoked refresh token"));

    if (storedToken.getExpiresAt().isBefore(Instant.now())) {
      throw new IllegalArgumentException("Refresh token expired");
    }

    storedToken.setRevoked(true);
    refreshTokenRepository.save(storedToken);

    User user =
        userRepository
            .findById(UUID.fromString(userId))
            .orElseThrow(() -> new IllegalArgumentException("User not found"));

    log.info("Token refreshed for user: {}", user.getEmail());
    return buildAuthResponse(user);
  }

  @Transactional
  public void changePassword(UUID userId, ChangePasswordRequest request) {
    User user =
        userRepository
            .findById(userId)
            .orElseThrow(() -> new IllegalArgumentException("User not found"));

    if (!passwordEncoder.matches(request.getCurrentPassword(), user.getPasswordHash())) {
      throw new IllegalArgumentException("Current password is incorrect");
    }

    user.setPasswordHash(passwordEncoder.encode(request.getNewPassword()));
    userRepository.save(user);

    refreshTokenRepository.revokeAllByUserId(userId);
    log.info("Password changed for user: {}", userId);
  }

  @Transactional
  public void logout(UUID userId) {
    refreshTokenRepository.revokeAllByUserId(userId);
    log.info("User logged out: {}", userId);
  }

  private AuthResponse buildAuthResponse(User user) {
    String accessToken = jwtTokenProvider.generateAccessToken(user);
    String refreshTokenStr = jwtTokenProvider.generateRefreshToken(user);

    String jti = jwtTokenProvider.extractJti(refreshTokenStr);
    RefreshToken refreshToken = new RefreshToken();
    refreshToken.setUser(user);
    refreshToken.setTokenId(jti);
    refreshToken.setExpiresAt(
        Instant.now().plus(jwtTokenProvider.getRefreshTokenExpiry(), ChronoUnit.SECONDS));
    refreshTokenRepository.save(refreshToken);

    return new AuthResponse(
        accessToken,
        refreshTokenStr,
        "Bearer",
        jwtTokenProvider.getAccessTokenExpiry(),
        new AuthResponse.UserDto(
            user.getId().toString(), user.getEmail(), user.getDisplayName(), user.getAvatarUrl()));
  }
}
