package com.otterworks.auth.service;

import com.otterworks.auth.exception.LoginThrottledException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Per-account failed-login throttle. After {@code maxFailures} rejected logins for one email within
 * {@code window}, that email is locked for {@code lockout}, whatever address the attempts come
 * from. Unknown emails are tracked the same way so the lock does not reveal which accounts exist.
 * State is in memory and bounded to {@code maxTrackedAccounts} entries (least recently used first).
 */
@Component
public class LoginAttemptThrottle {

  private static final class Attempts {
    int failures;
    Instant windowStart;
    Instant lockedUntil = Instant.MIN;
  }

  private final int maxFailures;
  private final Duration window;
  private final Duration lockout;
  private final Clock clock;
  private final Map<String, Attempts> attempts;

  @Autowired
  public LoginAttemptThrottle(
      @Value("${auth.login-throttle.max-failures:5}") int maxFailures,
      @Value("${auth.login-throttle.window-seconds:900}") long windowSeconds,
      @Value("${auth.login-throttle.lockout-seconds:900}") long lockoutSeconds,
      @Value("${auth.login-throttle.max-tracked-accounts:100000}") int maxTrackedAccounts) {
    this(
        maxFailures,
        Duration.ofSeconds(windowSeconds),
        Duration.ofSeconds(lockoutSeconds),
        maxTrackedAccounts,
        Clock.systemUTC());
  }

  LoginAttemptThrottle(
      int maxFailures, Duration window, Duration lockout, int maxTrackedAccounts, Clock clock) {
    if (maxFailures < 1 || maxTrackedAccounts < 1) {
      throw new IllegalStateException(
          "auth.login-throttle.max-failures and max-tracked-accounts must be positive");
    }
    this.maxFailures = maxFailures;
    this.window = window;
    this.lockout = lockout;
    this.clock = clock;
    this.attempts =
        new LinkedHashMap<>(16, 0.75f, true) {
          @Override
          protected boolean removeEldestEntry(Map.Entry<String, Attempts> eldest) {
            return size() > maxTrackedAccounts;
          }
        };
  }

  /** Throws {@link LoginThrottledException} while the account is locked. */
  public synchronized void checkAllowed(String email) {
    Attempts a = attempts.get(key(email));
    if (a == null) {
      return;
    }
    Instant now = clock.instant();
    if (now.isBefore(a.lockedUntil)) {
      long seconds = Duration.between(now, a.lockedUntil).toSeconds();
      throw new LoginThrottledException(Math.max(1, seconds));
    }
  }

  public synchronized void recordFailure(String email) {
    Instant now = clock.instant();
    Attempts a = attempts.computeIfAbsent(key(email), k -> new Attempts());
    if (a.windowStart == null || !now.isBefore(a.windowStart.plus(window))) {
      a.failures = 0;
      a.windowStart = now;
    }
    a.failures++;
    if (a.failures >= maxFailures) {
      a.lockedUntil = now.plus(lockout);
      a.failures = 0;
      a.windowStart = null;
    }
  }

  public synchronized void recordSuccess(String email) {
    attempts.remove(key(email));
  }

  synchronized int trackedAccounts() {
    return attempts.size();
  }

  private static String key(String email) {
    return email == null ? "" : email.trim().toLowerCase(Locale.ROOT);
  }
}
