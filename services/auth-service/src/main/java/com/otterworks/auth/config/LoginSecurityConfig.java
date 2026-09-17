package com.otterworks.auth.config;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConfigurationProperties(prefix = "auth.login")
@Getter
@Setter
public class LoginSecurityConfig {

  /** Failed attempts tolerated for one account before it is locked. */
  private int maxFailedAttempts = 5;

  /** Lockout length applied at the threshold; doubled for each further failure. */
  private long lockoutSeconds = 60;

  /** Upper bound on the exponential backoff. */
  private long maxLockoutSeconds = 3600;

  /** Idle period after which an account's failure counter is forgotten. */
  private long failureWindowSeconds = 900;

  /** Login attempts allowed per credential within the throttle window, whatever the source. */
  private int maxAttemptsPerCredential = 20;

  /** Window the per-credential throttle counts within. */
  private long credentialWindowSeconds = 60;
}
