package com.otterworks.auth.config;

import java.util.Arrays;
import org.flywaydb.core.api.MigrationInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.flyway.FlywayMigrationStrategy;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class FlywayConfig {

  /**
   * Checksum of V1 before the committed admin password hash was removed from it. Databases that
   * applied that version are realigned once so validation passes; V5 revokes the leaked hash.
   */
  static final int LEGACY_V1_CHECKSUM = -1077113232;

  private static final Logger log = LoggerFactory.getLogger(FlywayConfig.class);

  @Bean
  public FlywayMigrationStrategy flywayMigrationStrategy() {
    return flyway -> {
      boolean legacyV1Applied =
          Arrays.stream(flyway.info().applied()).anyMatch(FlywayConfig::isLegacyV1);
      if (legacyV1Applied) {
        log.info("Realigning Flyway checksum for V1 after removal of the seeded admin hash");
        flyway.repair();
      }
      flyway.migrate();
    };
  }

  private static boolean isLegacyV1(MigrationInfo info) {
    return info.getVersion() != null
        && "1".equals(info.getVersion().getVersion())
        && Integer.valueOf(LEGACY_V1_CHECKSUM).equals(info.getChecksum());
  }
}
