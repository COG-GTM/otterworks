package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

import com.otterworks.auth.config.LoginSecurityConfig;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.exception.AccountLockedException;
import com.otterworks.auth.exception.TooManyLoginAttemptsException;
import com.otterworks.auth.repository.UserRepository;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class LoginAttemptServiceTest {

  @Mock private UserRepository userRepository;

  private LoginSecurityConfig config;
  private LoginAttemptService loginAttemptService;
  private User user;

  @BeforeEach
  void setUp() {
    config = new LoginSecurityConfig();
    config.setMaxFailedAttempts(3);
    config.setLockoutSeconds(60);
    config.setMaxLockoutSeconds(600);
    config.setFailureWindowSeconds(900);
    config.setMaxAttemptsPerCredential(5);
    config.setCredentialWindowSeconds(60);
    loginAttemptService = new LoginAttemptService(userRepository, config);

    user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("victim@otterworks.dev");
  }

  @Test
  void recordFailure_shouldCountWithoutLockingBelowThreshold() {
    loginAttemptService.recordFailure(user);

    assertThat(user.getFailedLoginAttempts()).isEqualTo(1);
    assertThat(user.getLockoutUntil()).isNull();
    verify(userRepository).recordFailedLogin(eq(user.getId()), eq(1), any(), isNull());
  }

  @Test
  void recordFailure_shouldLockAccountAtThreshold() {
    user.setFailedLoginAttempts(2);
    user.setLastFailedLoginAt(Instant.now());

    loginAttemptService.recordFailure(user);

    assertThat(user.getFailedLoginAttempts()).isEqualTo(3);
    assertThat(user.getLockoutUntil())
        .isNotNull()
        .isBetween(Instant.now().plusSeconds(55), Instant.now().plusSeconds(65));
  }

  @Test
  void recordFailure_shouldDoubleTheLockoutForEachFurtherFailure() {
    user.setFailedLoginAttempts(4);
    user.setLastFailedLoginAt(Instant.now());
    user.setLockoutUntil(Instant.now().minusSeconds(1));

    loginAttemptService.recordFailure(user);

    assertThat(user.getFailedLoginAttempts()).isEqualTo(5);
    assertThat(user.getLockoutUntil())
        .isBetween(Instant.now().plusSeconds(235), Instant.now().plusSeconds(245));
  }

  @Test
  void recordFailure_shouldCapTheLockoutAtTheConfiguredMaximum() {
    user.setFailedLoginAttempts(20);
    user.setLastFailedLoginAt(Instant.now());
    user.setLockoutUntil(Instant.now().minusSeconds(1));

    loginAttemptService.recordFailure(user);

    assertThat(user.getLockoutUntil())
        .isBetween(
            Instant.now().plusSeconds(config.getMaxLockoutSeconds() - 5),
            Instant.now().plusSeconds(config.getMaxLockoutSeconds() + 5));
  }

  @Test
  void recordFailure_shouldForgetFailuresOlderThanTheWindow() {
    user.setFailedLoginAttempts(2);
    user.setLastFailedLoginAt(Instant.now().minusSeconds(config.getFailureWindowSeconds() + 1));

    loginAttemptService.recordFailure(user);

    assertThat(user.getFailedLoginAttempts()).isEqualTo(1);
    assertThat(user.getLockoutUntil()).isNull();
  }

  @Test
  void checkAccountLock_shouldRejectWhileTheLockoutIsInForce() {
    user.setLockoutUntil(Instant.now().plusSeconds(120));

    assertThatThrownBy(() -> loginAttemptService.checkAccountLock(user))
        .isInstanceOf(AccountLockedException.class)
        .satisfies(
            ex -> assertThat(((AccountLockedException) ex).getRetryAfterSeconds()).isPositive());
  }

  @Test
  void checkAccountLock_shouldAllowOnceTheLockoutHasExpired() {
    user.setLockoutUntil(Instant.now().minusSeconds(1));

    assertThatCode(() -> loginAttemptService.checkAccountLock(user)).doesNotThrowAnyException();
  }

  @Test
  void recordSuccess_shouldClearTheFailureState() {
    user.setFailedLoginAttempts(4);
    user.setLastFailedLoginAt(Instant.now());
    user.setLockoutUntil(Instant.now().minusSeconds(1));

    loginAttemptService.recordSuccess(user);

    assertThat(user.getFailedLoginAttempts()).isZero();
    assertThat(user.getLastFailedLoginAt()).isNull();
    assertThat(user.getLockoutUntil()).isNull();
  }

  @Test
  void checkCredentialThrottle_shouldRejectOnceTheAllowanceIsSpent() {
    for (int i = 0; i < config.getMaxAttemptsPerCredential(); i++) {
      loginAttemptService.checkCredentialThrottle("stuffed@otterworks.dev");
    }

    assertThatThrownBy(() -> loginAttemptService.checkCredentialThrottle("stuffed@otterworks.dev"))
        .isInstanceOf(TooManyLoginAttemptsException.class);
  }

  @Test
  void checkCredentialThrottle_shouldCountOneCredentialRegardlessOfCasing() {
    for (int i = 0; i < config.getMaxAttemptsPerCredential(); i++) {
      loginAttemptService.checkCredentialThrottle("Stuffed@Otterworks.dev");
    }

    assertThatThrownBy(
            () -> loginAttemptService.checkCredentialThrottle(" stuffed@otterworks.dev "))
        .isInstanceOf(TooManyLoginAttemptsException.class);
  }

  @Test
  void checkCredentialThrottle_shouldKeepCredentialsIndependent() {
    for (int i = 0; i < config.getMaxAttemptsPerCredential(); i++) {
      loginAttemptService.checkCredentialThrottle("one@otterworks.dev");
    }

    assertThatCode(() -> loginAttemptService.checkCredentialThrottle("two@otterworks.dev"))
        .doesNotThrowAnyException();
  }

  @Test
  void recordFailure_shouldPersistTheLockoutDeadline() {
    user.setFailedLoginAttempts(2);
    user.setLastFailedLoginAt(Instant.now());

    loginAttemptService.recordFailure(user);

    ArgumentCaptor<Instant> lockout = ArgumentCaptor.forClass(Instant.class);
    verify(userRepository).recordFailedLogin(eq(user.getId()), eq(3), any(), lockout.capture());
    assertThat(lockout.getValue()).isAfter(Instant.now());
  }
}
