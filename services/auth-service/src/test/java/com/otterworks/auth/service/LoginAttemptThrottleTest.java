package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;

import com.otterworks.auth.exception.LoginThrottledException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class LoginAttemptThrottleTest {

  private static final class MutableClock extends Clock {
    Instant now = Instant.parse("2026-10-26T12:00:00Z");

    @Override
    public java.time.ZoneId getZone() {
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

  private MutableClock clock;
  private LoginAttemptThrottle throttle;

  @BeforeEach
  void setUp() {
    clock = new MutableClock();
    throttle =
        new LoginAttemptThrottle(3, Duration.ofMinutes(15), Duration.ofMinutes(15), 100, clock);
  }

  @Test
  void locksAccountAfterMaxAttempts() {
    throttle.beginAttempt("a@otterworks.dev");
    throttle.beginAttempt("a@otterworks.dev");
    throttle.beginAttempt("a@otterworks.dev");

    assertThatThrownBy(() -> throttle.beginAttempt("a@otterworks.dev"))
        .isInstanceOf(LoginThrottledException.class)
        .satisfies(
            ex -> assertThat(((LoginThrottledException) ex).getRetryAfterSeconds()).isEqualTo(900));
  }

  @Test
  void keyIsCaseAndWhitespaceInsensitive() {
    throttle.beginAttempt("a@otterworks.dev");
    throttle.beginAttempt(" A@OtterWorks.dev");
    throttle.beginAttempt("A@OTTERWORKS.DEV ");

    assertThatThrownBy(() -> throttle.beginAttempt("a@otterworks.dev"))
        .isInstanceOf(LoginThrottledException.class);
  }

  @Test
  void lockIsPerAccount() {
    for (int i = 0; i < 3; i++) {
      throttle.beginAttempt("victim@otterworks.dev");
    }
    throttle.beginAttempt("other@otterworks.dev");
  }

  @Test
  void lockExpires() {
    for (int i = 0; i < 3; i++) {
      throttle.beginAttempt("a@otterworks.dev");
    }
    clock.now = clock.now.plus(Duration.ofMinutes(15));
    throttle.beginAttempt("a@otterworks.dev");
  }

  @Test
  void attemptsOutsideWindowDoNotAccumulate() {
    throttle.beginAttempt("a@otterworks.dev");
    throttle.beginAttempt("a@otterworks.dev");
    clock.now = clock.now.plus(Duration.ofMinutes(16));
    throttle.beginAttempt("a@otterworks.dev");
    throttle.beginAttempt("a@otterworks.dev");

    throttle.beginAttempt("a@otterworks.dev");
  }

  @Test
  void successResetsAttempts() {
    throttle.beginAttempt("a@otterworks.dev");
    throttle.beginAttempt("a@otterworks.dev");
    throttle.recordSuccess("a@otterworks.dev");
    throttle.beginAttempt("a@otterworks.dev");
    throttle.beginAttempt("a@otterworks.dev");

    throttle.beginAttempt("a@otterworks.dev");
  }

  @Test
  void concurrentAttemptsCannotExceedLimit() throws Exception {
    ExecutorService pool = Executors.newFixedThreadPool(16);
    try {
      List<Callable<Boolean>> calls = new ArrayList<>();
      for (int i = 0; i < 64; i++) {
        calls.add(
            () -> {
              try {
                throttle.beginAttempt("a@otterworks.dev");
                return true;
              } catch (LoginThrottledException e) {
                return false;
              }
            });
      }
      long admitted = 0;
      for (Future<Boolean> f : pool.invokeAll(calls)) {
        if (f.get()) {
          admitted++;
        }
      }
      assertThat(admitted).isEqualTo(3);
    } finally {
      pool.shutdownNow();
    }
  }

  @Test
  void trackedAccountsAreBounded() {
    for (int i = 0; i < 1000; i++) {
      throttle.beginAttempt("user" + i + "@otterworks.dev");
    }
    assertThat(throttle.trackedAccounts()).isEqualTo(100);
  }

  @Test
  void unknownEmailsDoNotEvictLockedAccounts() {
    for (int i = 0; i < 3; i++) {
      throttle.beginAttempt("victim@otterworks.dev");
    }
    for (int i = 0; i < 1000; i++) {
      throttle.beginAttempt("user" + i + "@otterworks.dev");
    }

    assertThatThrownBy(() -> throttle.beginAttempt("victim@otterworks.dev"))
        .isInstanceOf(LoginThrottledException.class);
    assertThat(throttle.trackedAccounts()).isEqualTo(100);
  }
}
