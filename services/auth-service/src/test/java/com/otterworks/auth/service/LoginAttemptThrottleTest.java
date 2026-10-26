package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;

import com.otterworks.auth.exception.LoginThrottledException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
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
  void locksAccountAfterMaxFailures() {
    throttle.recordFailure("a@otterworks.dev");
    throttle.recordFailure("a@otterworks.dev");
    throttle.checkAllowed("a@otterworks.dev");
    throttle.recordFailure("a@otterworks.dev");

    assertThatThrownBy(() -> throttle.checkAllowed("a@otterworks.dev"))
        .isInstanceOf(LoginThrottledException.class)
        .satisfies(
            ex ->
                assertThat(((LoginThrottledException) ex).getRetryAfterSeconds()).isEqualTo(900));
  }

  @Test
  void keyIsCaseAndWhitespaceInsensitive() {
    throttle.recordFailure("a@otterworks.dev");
    throttle.recordFailure(" A@OtterWorks.dev");
    throttle.recordFailure("A@OTTERWORKS.DEV ");

    assertThatThrownBy(() -> throttle.checkAllowed("a@otterworks.dev"))
        .isInstanceOf(LoginThrottledException.class);
  }

  @Test
  void lockIsPerAccount() {
    for (int i = 0; i < 3; i++) {
      throttle.recordFailure("victim@otterworks.dev");
    }
    throttle.checkAllowed("other@otterworks.dev");
  }

  @Test
  void lockExpires() {
    for (int i = 0; i < 3; i++) {
      throttle.recordFailure("a@otterworks.dev");
    }
    clock.now = clock.now.plus(Duration.ofMinutes(15));
    throttle.checkAllowed("a@otterworks.dev");
  }

  @Test
  void failuresOutsideWindowDoNotAccumulate() {
    throttle.recordFailure("a@otterworks.dev");
    throttle.recordFailure("a@otterworks.dev");
    clock.now = clock.now.plus(Duration.ofMinutes(16));
    throttle.recordFailure("a@otterworks.dev");

    throttle.checkAllowed("a@otterworks.dev");
  }

  @Test
  void successResetsFailures() {
    throttle.recordFailure("a@otterworks.dev");
    throttle.recordFailure("a@otterworks.dev");
    throttle.recordSuccess("a@otterworks.dev");
    throttle.recordFailure("a@otterworks.dev");
    throttle.recordFailure("a@otterworks.dev");

    throttle.checkAllowed("a@otterworks.dev");
  }

  @Test
  void trackedAccountsAreBounded() {
    for (int i = 0; i < 1000; i++) {
      throttle.recordFailure("user" + i + "@otterworks.dev");
    }
    assertThat(throttle.trackedAccounts()).isEqualTo(100);
  }
}
