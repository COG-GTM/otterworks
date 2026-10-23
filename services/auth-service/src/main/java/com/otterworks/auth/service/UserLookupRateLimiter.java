package com.otterworks.auth.service;

import com.otterworks.auth.exception.RateLimitExceededException;
import java.time.Clock;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Component;

/**
 * Per-principal fixed-window budget for the share-recipient lookup endpoints, so a logged-in
 * account cannot use them to enumerate registered emails or harvest profiles in bulk. Admins
 * already have the full user listing and are exempt.
 */
@Component
public class UserLookupRateLimiter {

  private static final int MAX_TRACKED_KEYS = 10_000;

  private final int emailLimit;
  private final int idLimit;
  private final long windowMillis;
  private final Clock clock;
  private final Map<String, Window> windows = new ConcurrentHashMap<>();

  @Autowired
  public UserLookupRateLimiter(
      @Value("${otterworks.user-lookup.email-limit:20}") int emailLimit,
      @Value("${otterworks.user-lookup.id-limit:120}") int idLimit,
      @Value("${otterworks.user-lookup.window-seconds:60}") long windowSeconds) {
    this(emailLimit, idLimit, windowSeconds, Clock.systemUTC());
  }

  UserLookupRateLimiter(int emailLimit, int idLimit, long windowSeconds, Clock clock) {
    this.emailLimit = emailLimit;
    this.idLimit = idLimit;
    this.windowMillis = windowSeconds * 1000;
    this.clock = clock;
  }

  public void checkEmailLookup(Authentication authentication) {
    check("email:", authentication, emailLimit);
  }

  public void checkIdLookup(Authentication authentication) {
    check("id:", authentication, idLimit);
  }

  private void check(String bucket, Authentication authentication, int limit) {
    if (isAdmin(authentication)) {
      return;
    }
    long now = clock.millis();
    if (windows.size() > MAX_TRACKED_KEYS) {
      windows.values().removeIf(w -> now - w.start >= windowMillis);
    }
    String key = bucket + authentication.getName();
    Window window =
        windows.compute(
            key,
            (k, w) -> {
              if (w == null || now - w.start >= windowMillis) {
                return new Window(now, 1);
              }
              return new Window(w.start, w.count + 1);
            });
    if (window.count > limit) {
      long retryAfterMillis = windowMillis - (now - window.start);
      throw new RateLimitExceededException(Math.max(1, (retryAfterMillis + 999) / 1000));
    }
  }

  private static boolean isAdmin(Authentication authentication) {
    return authentication.getAuthorities().stream()
        .anyMatch(a -> "ROLE_ADMIN".equals(a.getAuthority()));
  }

  private record Window(long start, int count) {}
}
