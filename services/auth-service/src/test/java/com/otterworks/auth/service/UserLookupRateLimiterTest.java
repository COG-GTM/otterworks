package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;

import com.otterworks.auth.exception.RateLimitExceededException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;

class UserLookupRateLimiterTest {

  private static final class MutableClock extends Clock {
    private Instant now = Instant.parse("2026-01-01T00:00:00Z");

    void advance(Duration d) {
      now = now.plus(d);
    }

    @Override
    public ZoneOffset getZone() {
      return ZoneOffset.UTC;
    }

    @Override
    public Clock withZone(java.time.ZoneId zone) {
      return this;
    }

    @Override
    public Instant instant() {
      return now;
    }
  }

  private static Authentication user(String id) {
    return new UsernamePasswordAuthenticationToken(
        id, null, List.of(new SimpleGrantedAuthority("ROLE_USER")));
  }

  private static Authentication admin(String id) {
    return new UsernamePasswordAuthenticationToken(
        id, null, List.of(new SimpleGrantedAuthority("ROLE_ADMIN")));
  }

  @Test
  void emailLookups_blockedAfterMissBudgetSpent_untilMissWindowExpires() {
    MutableClock clock = new MutableClock();
    UserLookupRateLimiter limiter = new UserLookupRateLimiter(100, 100, 60, 3, 900, clock);
    Authentication prober = user("prober");

    for (int i = 0; i < 3; i++) {
      limiter.checkEmailLookup(prober);
    }

    assertThatThrownBy(() -> limiter.checkEmailLookup(prober))
        .isInstanceOf(RateLimitExceededException.class)
        .satisfies(
            e ->
                assertThat(((RateLimitExceededException) e).getRetryAfterSeconds()).isEqualTo(900));

    clock.advance(Duration.ofMinutes(5));
    assertThatThrownBy(() -> limiter.checkEmailLookup(prober))
        .isInstanceOf(RateLimitExceededException.class);

    clock.advance(Duration.ofMinutes(10));
    assertThatCode(() -> limiter.checkEmailLookup(prober)).doesNotThrowAnyException();
  }

  @Test
  void missBudget_isPerCaller_andDoesNotAffectIdLookups() {
    UserLookupRateLimiter limiter =
        new UserLookupRateLimiter(100, 100, 60, 1, 900, new MutableClock());
    Authentication prober = user("prober");
    limiter.checkEmailLookup(prober);

    assertThatThrownBy(() -> limiter.checkEmailLookup(prober))
        .isInstanceOf(RateLimitExceededException.class);
    assertThatCode(() -> limiter.checkIdLookup(prober)).doesNotThrowAnyException();
    assertThatCode(() -> limiter.checkEmailLookup(user("someone-else"))).doesNotThrowAnyException();
  }

  @Test
  void hits_areRefunded_soOnlyMissesSpendTheMissBudget() {
    UserLookupRateLimiter limiter =
        new UserLookupRateLimiter(100, 100, 60, 2, 900, new MutableClock());
    Authentication sharer = user("sharer");

    for (int i = 0; i < 10; i++) {
      limiter.checkEmailLookup(sharer);
      limiter.refundEmailMiss(sharer);
    }
    limiter.checkEmailLookup(sharer);
    limiter.checkEmailLookup(sharer);

    assertThatThrownBy(() -> limiter.checkEmailLookup(sharer))
        .isInstanceOf(RateLimitExceededException.class);
  }

  @Test
  void concurrentLookups_cannotExceedMissBudget() throws Exception {
    UserLookupRateLimiter limiter =
        new UserLookupRateLimiter(100, 100, 60, 10, 900, new MutableClock());
    Authentication prober = user("prober");
    int threads = 20;
    CountDownLatch start = new CountDownLatch(1);
    ExecutorService pool = Executors.newFixedThreadPool(threads);
    AtomicInteger admitted = new AtomicInteger();
    try {
      List<Future<?>> futures = new ArrayList<>();
      for (int i = 0; i < threads; i++) {
        futures.add(
            pool.submit(
                () -> {
                  start.await();
                  try {
                    limiter.checkEmailLookup(prober);
                    admitted.incrementAndGet();
                  } catch (RateLimitExceededException ignored) {
                    // expected once the budget is spent
                  }
                  return null;
                }));
      }
      start.countDown();
      for (Future<?> f : futures) {
        f.get();
      }
    } finally {
      pool.shutdownNow();
    }

    assertThat(admitted.get()).isEqualTo(10);
  }

  @Test
  void requestBudget_resetsAfterWindow() {
    MutableClock clock = new MutableClock();
    UserLookupRateLimiter limiter = new UserLookupRateLimiter(2, 2, 60, 10, 900, clock);
    Authentication caller = user("caller");

    limiter.checkEmailLookup(caller);
    limiter.checkEmailLookup(caller);
    assertThatThrownBy(() -> limiter.checkEmailLookup(caller))
        .isInstanceOf(RateLimitExceededException.class);

    clock.advance(Duration.ofSeconds(61));
    assertThatCode(() -> limiter.checkEmailLookup(caller)).doesNotThrowAnyException();
  }

  @Test
  void admins_areExempt() {
    UserLookupRateLimiter limiter = new UserLookupRateLimiter(1, 1, 60, 1, 900, new MutableClock());
    Authentication admin = admin("admin");
    for (int i = 0; i < 5; i++) {
      limiter.checkEmailLookup(admin);
      limiter.refundEmailMiss(admin);
      limiter.checkIdLookup(admin);
    }
  }
}
