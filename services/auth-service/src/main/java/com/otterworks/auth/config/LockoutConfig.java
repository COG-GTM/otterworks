package com.otterworks.auth.config;

import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import java.time.Duration;
import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.validation.annotation.Validated;

@Configuration
@ConfigurationProperties(prefix = "auth.lockout")
@Validated
@Getter
@Setter
public class LockoutConfig {
  @Min(1)
  private int maxAttempts = 5;

  @NotNull private Duration duration = Duration.ofMinutes(15);

  @AssertTrue(message = "auth.lockout.duration must be positive")
  public boolean isDurationPositive() {
    return duration == null || (!duration.isZero() && !duration.isNegative());
  }
}
