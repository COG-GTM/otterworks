package com.otterworks.auth.config;

import java.time.Duration;
import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConfigurationProperties(prefix = "auth.lockout")
@Getter
@Setter
public class LoginLockoutProperties {
  private int maxFailedAttempts = 5;
  private Duration lockoutDuration = Duration.ofMinutes(15);
}
