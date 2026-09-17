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
  void bindablePropertiesRoundTrip() {
    JwtConfig config = new JwtConfig();

    config.setSecret("jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac");
    config.setAccessTokenExpiry(900L);
    config.setRefreshTokenExpiry(604800L);

    assertThat(config.getSecret())
        .isEqualTo("jwt-secret-otterworks-must-be-at-least-32-bytes-long-for-hmac");
    assertThat(config.getAccessTokenExpiry()).isEqualTo(900L);
    assertThat(config.getRefreshTokenExpiry()).isEqualTo(604800L);
  }
}
