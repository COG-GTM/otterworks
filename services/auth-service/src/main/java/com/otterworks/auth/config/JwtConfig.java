package com.otterworks.auth.config;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConfigurationProperties(prefix = "jwt")
@Getter
@Setter
public class JwtConfig {
  private String secret;
  private String issuer = "otterworks-auth-service";
  private String audience = "otterworks";
  private long accessTokenExpiry = 3600;
  private long refreshTokenExpiry = 2592000;
}
