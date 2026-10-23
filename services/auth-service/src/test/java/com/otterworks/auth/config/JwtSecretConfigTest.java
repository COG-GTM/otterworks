package com.otterworks.auth.config;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.PropertySource;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.core.io.ClassPathResource;

class JwtSecretConfigTest {

  @Test
  void applicationYml_shouldNotShipAFallbackJwtSecret() throws Exception {
    StandardEnvironment env = new StandardEnvironment();
    env.getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
    env.getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
    for (PropertySource<?> source :
        new YamlPropertySourceLoader()
            .load("application", new ClassPathResource("application.yml"))) {
      env.getPropertySources().addLast(source);
    }

    assertThat(env.getProperty("jwt.secret")).isEmpty();
  }
}
