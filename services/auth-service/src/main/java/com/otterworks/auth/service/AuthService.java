package com.otterworks.auth.service;

import com.otterworks.auth.audit.AuditActor;
import com.otterworks.auth.audit.AuditClient;
import com.otterworks.auth.audit.AuditEvent;
import com.otterworks.auth.dto.AuthResponse;
import com.otterworks.auth.dto.ChangePasswordRequest;
import com.otterworks.auth.dto.LoginRequest;
import com.otterworks.auth.dto.RegisterRequest;
import com.otterworks.auth.entity.RefreshToken;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.security.JwtTokenProvider;
import io.jsonwebtoken.JwtException;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
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
  private final AuditClient auditClient;

  /** Compared against for unknown emails so both login failure paths cost one hash check. */
  private final String unknownUserPasswordHash;

  public AuthService(
      UserRepository userRepository,
      PasswordEncoder passwordEncoder,
      JwtTokenProvider jwtTokenProvider,
      RefreshTokenRepository refreshTokenRepository,
      AuditClient auditClient) {
    this.userRepository = userRepository;
    this.passwordEncoder = passwordEncoder;
    this.jwtTokenProvider = jwtTokenProvider;
    this.refreshTokenRepository = refreshTokenRepository;
    this.auditClient = auditClient;
    this.unknownUserPasswordHash = passwordEncoder.encode(UUID.randomUUID().toString());
  }

  @Transactional
  public AuthResponse register(RegisterRequest request) {
    if (userRepository.existsByEmail(request.getEmail())) {
      throw new IllegalArgumentException("Email already registered");
    }

    User user = new User();
    user.setEmail(request.getEmail());
    user.setPasswordHash(passwordEncoder.encode(request.getPassword()));
    user.setDisplayName(request.getDisplayName());
    user.setRoles(Set.of(User.Role.USER));
    user = userRepository.save(user);

    log.info("User registered: email={}", user.getEmail());
    auditClient.emit(userEvent(user, "auth.user.register", AuditEvent.OUTCOME_SUCCESS, null));
    auditClient.emit(
        userEvent(
            user,
            "permission.change",
            AuditEvent.OUTCOME_SUCCESS,
            Map.of("before", "", "after", rolesToString(user.getRoles()), "reason", "register")));
    return buildAuthResponse(user);
  }

  @Transactional
  public AuthResponse login(LoginRequest request) {
    Optional<User> found = userRepository.findByEmail(request.getEmail());
    // Always run one password check so unknown emails and wrong passwords take the same time.
    String passwordHash = found.map(User::getPasswordHash).orElse(unknownUserPasswordHash);
    boolean passwordMatches = passwordEncoder.matches(request.getPassword(), passwordHash);

    if (found.isEmpty() || !passwordMatches) {
      auditClient.emit(
          AuditEvent.builder()
              .userId(AuditEvent.ANONYMOUS)
              .actorType(AuditActor.TYPE_ANONYMOUS)
              .action("auth.login.failure")
              .resourceType("user")
              .resourceId(found.map(u -> u.getId().toString()).orElse("unknown"))
              .outcome(AuditEvent.OUTCOME_FAILURE)
              .details(
                  Map.of(
                      "reason",
                      found.isEmpty() ? "unknown_user" : "bad_password",
                      "attemptedEmail",
                      String.valueOf(request.getEmail())))
              .build());
      throw new IllegalArgumentException("Invalid credentials");
    }

    User user = found.get();
    user.setLastLoginAt(Instant.now());
    userRepository.save(user);

    log.info("User logged in: email={}", user.getEmail());
    auditClient.emit(userEvent(user, "auth.login.success", AuditEvent.OUTCOME_SUCCESS, null));
    return buildAuthResponse(user);
  }

  @Transactional
  public AuthResponse refreshToken(String token) {
    String jti;
    String userId;
    try {
      jti = jwtTokenProvider.extractJti(token);
      userId = jwtTokenProvider.validateRefreshTokenAndGetUserId(token);
    } catch (JwtException | IllegalArgumentException e) {
      auditRefreshDenied(AuditEvent.ANONYMOUS, "invalid_token");
      throw e;
    }

    Optional<RefreshToken> stored = refreshTokenRepository.findByTokenIdAndRevokedFalse(jti);
    if (stored.isEmpty()) {
      auditRefreshDenied(userId, "revoked_or_reused");
      throw new IllegalArgumentException("Invalid or revoked refresh token");
    }
    RefreshToken storedToken = stored.get();

    if (storedToken.getExpiresAt().isBefore(Instant.now())) {
      auditRefreshDenied(userId, "expired");
      throw new IllegalArgumentException("Refresh token expired");
    }

    storedToken.setRevoked(true);
    refreshTokenRepository.save(storedToken);

    Optional<User> found = userRepository.findById(UUID.fromString(userId));
    if (found.isEmpty()) {
      auditRefreshDenied(userId, "user_not_found");
      throw new IllegalArgumentException("User not found");
    }
    User user = found.get();

    log.info("Token refreshed for user: {}", user.getEmail());
    auditClient.emit(userEvent(user, "auth.token.refresh", AuditEvent.OUTCOME_SUCCESS, null));
    return buildAuthResponse(user);
  }

  @Transactional
  public void changePassword(UUID userId, ChangePasswordRequest request) {
    User user =
        userRepository
            .findById(userId)
            .orElseThrow(() -> new IllegalArgumentException("User not found"));

    if (!passwordEncoder.matches(request.getCurrentPassword(), user.getPasswordHash())) {
      auditClient.emit(
          userEvent(
              user,
              "auth.credential.change",
              AuditEvent.OUTCOME_FAILURE,
              Map.of("reason", "current_password_mismatch", "credential", "password")));
      throw new IllegalArgumentException("Current password is incorrect");
    }

    user.setPasswordHash(passwordEncoder.encode(request.getNewPassword()));
    userRepository.save(user);

    refreshTokenRepository.revokeAllByUserId(userId);
    log.info("Password changed for user: {}", userId);
    auditClient.emit(
        userEvent(
            user,
            "auth.credential.change",
            AuditEvent.OUTCOME_SUCCESS,
            Map.of("credential", "password", "refreshTokensRevoked", "true")));
  }

  @Transactional
  public void logout(UUID userId) {
    refreshTokenRepository.revokeAllByUserId(userId);
    log.info("User logged out: {}", userId);
    auditClient.emit(
        AuditEvent.builder()
            .userId(userId.toString())
            .actorType(AuditActor.currentActorType())
            .action("auth.logout")
            .resourceType("user")
            .resourceId(userId.toString())
            .outcome(AuditEvent.OUTCOME_SUCCESS)
            .build());
  }

  private void auditRefreshDenied(String userId, String reason) {
    boolean anonymous = AuditEvent.ANONYMOUS.equals(userId);
    auditClient.emit(
        AuditEvent.builder()
            .userId(userId)
            .actorType(anonymous ? AuditActor.TYPE_ANONYMOUS : AuditActor.TYPE_USER)
            .action("auth.token.refresh_denied")
            .resourceType("user")
            .resourceId(anonymous ? "unknown" : userId)
            .outcome(AuditEvent.OUTCOME_DENIED)
            .details(Map.of("reason", reason))
            .build());
  }

  private static AuditEvent userEvent(
      User user, String action, String outcome, Map<String, String> details) {
    String id = user.getId().toString();
    return AuditEvent.builder()
        .userId(id)
        .actorEmail(user.getEmail())
        .actorType(AuditActor.typeOf(user))
        .action(action)
        .resourceType("user")
        .resourceId(id)
        .outcome(outcome)
        .details(details)
        .build();
  }

  static String rolesToString(Set<User.Role> roles) {
    return roles == null
        ? ""
        : roles.stream().map(Enum::name).sorted().collect(Collectors.joining(","));
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
