package com.otterworks.auth.service;

import com.otterworks.auth.config.LoginSecurityConfig;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.exception.AccountLockedException;
import com.otterworks.auth.exception.TooManyLoginAttemptsException;
import com.otterworks.auth.repository.UserRepository;
import java.time.Duration;
import java.time.Instant;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Throttles login attempts per account and per credential. Both counters are keyed on the
 * credential rather than the caller's address, so rotating source addresses does not buy an
 * attacker more attempts.
 */
@Service
public class LoginAttemptService {

  private static final Logger log = LoggerFactory.getLogger(LoginAttemptService.class);
  private static final int MAX_TRACKED_CREDENTIALS = 50_000;

  private final UserRepository userRepository;
  private final LoginSecurityConfig config;
  private final Map<String, CredentialWindow> credentialWindows = new ConcurrentHashMap<>();

  public LoginAttemptService(UserRepository userRepository, LoginSecurityConfig config) {
    this.userRepository = userRepository;
    this.config = config;
  }

  /**
   * Counts an attempt against the credential, whatever the source address it arrived from, and
   * rejects it once the window's allowance is spent. Covers credentials with no account behind
   * them, which have no per-account counter to lock.
   */
  public void checkCredentialThrottle(String email) {
    Instant now = Instant.now();
    if (credentialWindows.size() > MAX_TRACKED_CREDENTIALS) {
      credentialWindows.values().removeIf(window -> window.isExpired(now));
    }

    CredentialWindow window =
        credentialWindows.compute(
            key(email),
            (k, existing) ->
                existing == null || existing.isExpired(now) ? new CredentialWindow(now) : existing);
    if (window.attempts.incrementAndGet() > config.getMaxAttemptsPerCredential()) {
      throw new TooManyLoginAttemptsException(window.secondsRemaining(now));
    }
  }

  /** Rejects the attempt while the account's lockout is still in force. */
  public void checkAccountLock(User user) {
    Instant lockoutUntil = user.getLockoutUntil();
    Instant now = Instant.now();
    if (lockoutUntil != null && lockoutUntil.isAfter(now)) {
      throw new AccountLockedException(secondsUntil(now, lockoutUntil));
    }
  }

  /**
   * Records a failed attempt and locks the account once the threshold is reached, for a period that
   * doubles with every further failure. Runs in its own transaction so the counter survives the
   * rollback of the rejected login.
   */
  @Transactional(propagation = Propagation.REQUIRES_NEW)
  public void recordFailure(User user) {
    Instant now = Instant.now();
    int attempts = currentAttempts(user, now) + 1;

    Instant lockoutUntil = null;
    if (attempts >= config.getMaxFailedAttempts()) {
      lockoutUntil = now.plusSeconds(lockoutSeconds(attempts));
      log.warn(
          "audit event=account_locked userId={} email={} failedAttempts={} lockedUntil={}",
          user.getId(),
          user.getEmail(),
          attempts,
          lockoutUntil);
    }

    userRepository.recordFailedLogin(user.getId(), attempts, now, lockoutUntil);
    user.setFailedLoginAttempts(attempts);
    user.setLastFailedLoginAt(now);
    user.setLockoutUntil(lockoutUntil);
  }

  /** Clears the account's failure state after a successful login. */
  public void recordSuccess(User user) {
    user.setFailedLoginAttempts(0);
    user.setLastFailedLoginAt(null);
    user.setLockoutUntil(null);
    credentialWindows.remove(key(user.getEmail()));
  }

  /** Failures older than the window, with no lockout in force, no longer count. */
  private int currentAttempts(User user, Instant now) {
    Instant lastFailure = user.getLastFailedLoginAt();
    boolean expired =
        lastFailure == null
            || lastFailure.plusSeconds(config.getFailureWindowSeconds()).isBefore(now);
    boolean locked = user.getLockoutUntil() != null && user.getLockoutUntil().isAfter(now);
    return expired && !locked ? 0 : user.getFailedLoginAttempts();
  }

  private long lockoutSeconds(int attempts) {
    int doublings = Math.min(attempts - config.getMaxFailedAttempts(), 20);
    long seconds = config.getLockoutSeconds() << doublings;
    return Math.min(seconds, config.getMaxLockoutSeconds());
  }

  private long secondsUntil(Instant now, Instant until) {
    return Math.max(1, Duration.between(now, until).toSeconds());
  }

  private String key(String email) {
    return email == null ? "" : email.trim().toLowerCase(Locale.ROOT);
  }

  private final class CredentialWindow {
    private final Instant startedAt;
    private final AtomicInteger attempts = new AtomicInteger();

    private CredentialWindow(Instant startedAt) {
      this.startedAt = startedAt;
    }

    private boolean isExpired(Instant now) {
      return startedAt.plusSeconds(config.getCredentialWindowSeconds()).isBefore(now);
    }

    private long secondsRemaining(Instant now) {
      return secondsUntil(now, startedAt.plusSeconds(config.getCredentialWindowSeconds()));
    }
  }
}
