package com.otterworks.auth.config;

import static org.assertj.core.api.Assertions.assertThat;

import jakarta.validation.Validation;
import jakarta.validation.Validator;
import java.time.Duration;
import org.junit.jupiter.api.Test;

class LockoutConfigTest {

  private final Validator validator = Validation.buildDefaultValidatorFactory().getValidator();

  @Test
  void defaultsAreValid() {
    assertThat(validator.validate(new LockoutConfig())).isEmpty();
  }

  @Test
  void rejectsZeroDuration() {
    LockoutConfig config = new LockoutConfig();
    config.setDuration(Duration.ZERO);
    assertThat(validator.validate(config)).isNotEmpty();
  }

  @Test
  void rejectsNegativeDuration() {
    LockoutConfig config = new LockoutConfig();
    config.setDuration(Duration.ofMinutes(-1));
    assertThat(validator.validate(config)).isNotEmpty();
  }

  @Test
  void rejectsMaxAttemptsBelowOne() {
    LockoutConfig config = new LockoutConfig();
    config.setMaxAttempts(0);
    assertThat(validator.validate(config)).isNotEmpty();
  }
}
