package com.otterworks.auth.config;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class JwtConfigTest {

  @Test
  void expiriesDefaultToOneHourAndThirtyDays() {
    JwtConfig config = new JwtConfig();

    assertThat(config.getSecret()).isNull();
    assertThat(config.getAccessTokenExpiry()).isEqualTo(3600L);
    assertThat(config.getRefreshTokenExpiry()).isEqualTo(2592000L);
  }

  @Test
  void bindingOverridesTheDefaults() {
    JwtConfig config = new JwtConfig();
    config.setSecret("configured-secret");
    config.setAccessTokenExpiry(900L);
    config.setRefreshTokenExpiry(86400L);

    assertThat(config.getSecret()).isEqualTo("configured-secret");
    assertThat(config.getAccessTokenExpiry()).isEqualTo(900L);
    assertThat(config.getRefreshTokenExpiry()).isEqualTo(86400L);
  }
}
