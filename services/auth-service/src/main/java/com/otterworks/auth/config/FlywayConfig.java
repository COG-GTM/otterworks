package com.otterworks.auth.config;

import java.util.Arrays;
import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationInfo;
import org.flywaydb.core.api.configuration.Configuration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.flyway.FlywayMigrationStrategy;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.core.JdbcTemplate;

@org.springframework.context.annotation.Configuration
public class FlywayConfig {

  /** Checksum of V1 while it still seeded the admin account with a committed password hash. */
  static final int LEGACY_V1_CHECKSUM = -1077113232;

  /** Checksum of V1 after the seeded admin account was removed. */
  static final int CURRENT_V1_CHECKSUM = 1501650846;

  private static final Logger log = LoggerFactory.getLogger(FlywayConfig.class);

  @Bean
  public FlywayMigrationStrategy flywayMigrationStrategy() {
    return flyway -> {
      realignLegacyV1Checksum(flyway);
      flyway.migrate();
    };
  }

  /**
   * Rewrites only the history checksum of a V1 applied before the seeded admin hash was removed, so
   * any other drift still fails validation. V5 revokes the leaked hash on those databases.
   */
  static void realignLegacyV1Checksum(Flyway flyway) {
    boolean legacyV1Applied =
        Arrays.stream(flyway.info().applied()).anyMatch(FlywayConfig::isLegacyV1);
    if (!legacyV1Applied) {
      return;
    }

    Configuration config = flyway.getConfiguration();
    String table =
        config.getDefaultSchema() == null
            ? quote(config.getTable())
            : quote(config.getDefaultSchema()) + "." + quote(config.getTable());
    int updated =
        new JdbcTemplate(config.getDataSource())
            .update(
                "UPDATE " + table + " SET checksum = ? WHERE version = '1' AND checksum = ?",
                CURRENT_V1_CHECKSUM,
                LEGACY_V1_CHECKSUM);
    log.info(
        "Realigned Flyway V1 checksum after removal of the seeded admin hash: rows={}", updated);
  }

  private static boolean isLegacyV1(MigrationInfo info) {
    return info.getVersion() != null
        && "1".equals(info.getVersion().getVersion())
        && Integer.valueOf(LEGACY_V1_CHECKSUM).equals(info.getChecksum());
  }

  private static String quote(String identifier) {
    return "\"" + identifier.replace("\"", "\"\"") + "\"";
  }
}
