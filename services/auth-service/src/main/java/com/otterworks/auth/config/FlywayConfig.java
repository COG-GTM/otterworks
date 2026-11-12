package com.otterworks.auth.config;

import java.sql.SQLException;
import org.springframework.boot.autoconfigure.flyway.FlywayMigrationStrategy;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class FlywayConfig {

  @Bean
  public FlywayMigrationStrategy flywayMigrationStrategy() {
    return flyway -> {
      try {
        FlywayChecksumRealigner.realign(flyway.getConfiguration());
      } catch (SQLException e) {
        throw new IllegalStateException("Failed to realign Flyway checksums", e);
      }
      flyway.migrate();
    };
  }
}
