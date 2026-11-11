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
 * Per-principal fixed-window budgets for the share-recipient lookup endpoints, so a logged-in
 * account cannot use them to enumerate registered emails or harvest profiles in bulk. Email lookups
 * that miss draw from a separate, longer-lived budget: legitimate sharing rarely misses, guessing
 * mostly does, and once it is spent every email lookup (hit or miss) gets the same 429. Admins
 * already have the full user listing and are exempt.
 */
@Component
public class UserLookupRateLimiter {

  private static final int MAX_TRACKED_KEYS = 10_000;

  private final Limit emailLimit;
  private final Limit emailMissLimit;
  private final Limit idLimit;
  private final Clock clock;
  private final Map<String, Window> windows = new ConcurrentHashMap<>();

  @Autowired
  public UserLookupRateLimiter(
      @Value("${otterworks.user-lookup.email-limit:20}") int emailLimit,
      @Value("${otterworks.user-lookup.id-limit:120}") int idLimit,
      @Value("${otterworks.user-lookup.window-seconds:60}") long windowSeconds,
      @Value("${otterworks.user-lookup.email-miss-limit:10}") int emailMissLimit,
      @Value("${otterworks.user-lookup.email-miss-window-seconds:900}")
          long emailMissWindowSeconds) {
    this(
        emailLimit,
        idLimit,
        windowSeconds,
        emailMissLimit,
        emailMissWindowSeconds,
        Clock.systemUTC());
  }

  UserLookupRateLimiter(
      int emailLimit,
      int idLimit,
      long windowSeconds,
      int emailMissLimit,
      long emailMissWindowSeconds,
      Clock clock) {
    this.emailLimit = new Limit("email:", emailLimit, windowSeconds * 1000);
    this.idLimit = new Limit("id:", idLimit, windowSeconds * 1000);
    this.emailMissLimit = new Limit("email-miss:", emailMissLimit, emailMissWindowSeconds * 1000);
    this.clock = clock;
  }

  /**
   * Admits an email lookup and provisionally charges it to the miss budget, so concurrent requests
   * cannot all pass before their misses are counted. Call {@link #refundEmailMiss} when it matches.
   */
  public void checkEmailLookup(Authentication authentication) {
    if (isAdmin(authentication)) {
      return;
    }
    long now = clock.millis();
    String principal = authentication.getName();
    consume(emailLimit, principal, now);
    reserve(emailMissLimit, principal, now);
  }

  /**
   * Returns the provisional miss charge taken by {@link #checkEmailLookup} for a lookup that hit.
   */
  public void refundEmailMiss(Authentication authentication) {
    if (isAdmin(authentication)) {
      return;
    }
    long now = clock.millis();
    windows.computeIfPresent(
        emailMissLimit.key(authentication.getName()),
        (k, w) ->
            now - w.start < w.windowMillis && w.count > 0
                ? new Window(w.start, w.count - 1, w.windowMillis)
                : w);
  }

  public void checkIdLookup(Authentication authentication) {
    if (isAdmin(authentication)) {
      return;
    }
    consume(idLimit, authentication.getName(), clock.millis());
  }

  private void consume(Limit limit, String principal, long now) {
    evictExpired(now);
    Window window = windows.compute(limit.key(principal), (k, w) -> next(limit, w, now));
    if (window.count > limit.max) {
      throw new RateLimitExceededException(retryAfterSeconds(limit, window, now));
    }
  }

  private void reserve(Limit limit, String principal, long now) {
    evictExpired(now);
    Window[] exhausted = new Window[1];
    windows.compute(
        limit.key(principal),
        (k, w) -> {
          if (w != null && now - w.start < limit.windowMillis && w.count >= limit.max) {
            exhausted[0] = w;
            return w;
          }
          return next(limit, w, now);
        });
    if (exhausted[0] != null) {
      throw new RateLimitExceededException(retryAfterSeconds(limit, exhausted[0], now));
    }
  }

  private static Window next(Limit limit, Window current, long now) {
    if (current == null || now - current.start >= limit.windowMillis) {
      return new Window(now, 1, limit.windowMillis);
    }
    return new Window(current.start, current.count + 1, limit.windowMillis);
  }

  private void evictExpired(long now) {
    if (windows.size() > MAX_TRACKED_KEYS) {
      windows.values().removeIf(w -> now - w.start >= w.windowMillis);
    }
  }

  private static long retryAfterSeconds(Limit limit, Window window, long now) {
    long retryAfterMillis = limit.windowMillis - (now - window.start);
    return Math.max(1, (retryAfterMillis + 999) / 1000);
  }

  private static boolean isAdmin(Authentication authentication) {
    return authentication.getAuthorities().stream()
        .anyMatch(a -> "ROLE_ADMIN".equals(a.getAuthority()));
  }

  private record Limit(String bucket, int max, long windowMillis) {
    String key(String principal) {
      return bucket + principal;
    }
  }

  private record Window(long start, int count, long windowMillis) {}
}
