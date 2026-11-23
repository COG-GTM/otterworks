package com.otterworks.auth.service;

import com.otterworks.auth.exception.LoginThrottledException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Per-account failed-login throttle. After {@code maxFailures} unsuccessful logins for one email
 * within {@code window}, that email is locked for {@code lockout}, whatever address the attempts
 * come from. Unknown emails are tracked the same way so the lock does not reveal which accounts
 * exist. State is in memory and bounded to {@code maxTrackedAccounts} entries; when full, the least
 * recently used unlocked entry is evicted before any locked one.
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
  private final int maxTrackedAccounts;
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
    this.maxTrackedAccounts = maxTrackedAccounts;
    this.clock = clock;
    this.attempts = new LinkedHashMap<>(16, 0.75f, true);
  }

  /**
   * Reserves a login attempt, counting it as a failure until {@link #recordSuccess} clears it so
   * concurrent attempts cannot all pass before the lock is set. Throws {@link
   * LoginThrottledException} while the account is locked.
   */
  public synchronized void beginAttempt(String email) {
    Instant now = clock.instant();
    String key = key(email);
    Attempts a = attempts.get(key);
    if (a != null && now.isBefore(a.lockedUntil)) {
      long seconds = Duration.between(now, a.lockedUntil).toSeconds();
      throw new LoginThrottledException(Math.max(1, seconds));
    }
    if (a == null) {
      a = new Attempts();
      attempts.put(key, a);
      evictIfFull(key, now);
    }
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

  private void evictIfFull(String keep, Instant now) {
    if (attempts.size() <= maxTrackedAccounts) {
      return;
    }
    String eldest = null;
    Iterator<Map.Entry<String, Attempts>> it = attempts.entrySet().iterator();
    while (it.hasNext()) {
      Map.Entry<String, Attempts> e = it.next();
      if (e.getKey().equals(keep)) {
        continue;
      }
      if (eldest == null) {
        eldest = e.getKey();
      }
      if (!now.isBefore(e.getValue().lockedUntil)) {
        it.remove();
        return;
      }
    }
    attempts.remove(eldest);
  }

  synchronized int trackedAccounts() {
    return attempts.size();
  }

  private static String key(String email) {
    return email == null ? "" : email.trim().toLowerCase(Locale.ROOT);
  }
}
