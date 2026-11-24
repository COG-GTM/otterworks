package com.otterworks.auth.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class SecurityConfigTest {

  @ParameterizedTest
  @ValueSource(ints = {10, 12, 14})
  void requireValidStrength_acceptsCostsInRange(int strength) {
    assertThat(SecurityConfig.requireValidStrength(strength)).isEqualTo(strength);
  }

  @ParameterizedTest
  @ValueSource(ints = {4, 8, 9, 15, 31})
  void requireValidStrength_rejectsCostsOutOfRange(int strength) {
    assertThatThrownBy(() -> SecurityConfig.requireValidStrength(strength))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("security.bcrypt-strength");
  }

  @Test
  void passwordEncoder_usesConfiguredStrength() {
    SecurityConfig config = new SecurityConfig(null);
    String hash = config.passwordEncoder(11).encode("password123");
    assertThat(hash).startsWith("$2a$11$");
  }
}
