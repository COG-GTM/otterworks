package com.otterworks.auth.config;

import jakarta.validation.constraints.Positive;
import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.validation.annotation.Validated;

@Configuration
@ConfigurationProperties(prefix = "auth.login")
@Validated
@Getter
@Setter
public class LoginSecurityConfig {

  /** Failed attempts tolerated for one account before it is locked. */
  @Positive private int maxFailedAttempts = 5;

  /** Lockout length applied at the threshold; doubled for each further failure. */
  @Positive private long lockoutSeconds = 60;

  /** Upper bound on the exponential backoff. */
  @Positive private long maxLockoutSeconds = 3600;

  /** Idle period after which an account's failure counter is forgotten. */
  @Positive private long failureWindowSeconds = 900;

  /** Login attempts allowed per credential within the throttle window, whatever the source. */
  @Positive private int maxAttemptsPerCredential = 20;

  /** Window the per-credential throttle counts within. */
  @Positive private long credentialWindowSeconds = 60;
}
