package com.otterworks.auth.config;

import org.flywaydb.core.api.ErrorCode;
import org.flywaydb.core.api.output.ValidateOutput;
import org.flywaydb.core.api.output.ValidateResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.flyway.FlywayMigrationStrategy;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class FlywayConfig {

  /** V1 was edited to drop the default admin seed; V5 deletes that row from existing databases. */
  static final String REWRITTEN_MIGRATION_VERSION = "1";

  private static final Logger log = LoggerFactory.getLogger(FlywayConfig.class);

  @Bean
  public FlywayMigrationStrategy flywayMigrationStrategy() {
    return flyway -> {
      if (onlyRewrittenMigrationChecksumMismatch(flyway.validateWithResult())) {
        log.warn(
            "Realigning checksum of rewritten migration V{} before migrating",
            REWRITTEN_MIGRATION_VERSION);
        flyway.repair();
      }
      flyway.migrate();
    };
  }

  static boolean onlyRewrittenMigrationChecksumMismatch(ValidateResult result) {
    if (result.validationSuccessful
        || result.invalidMigrations == null
        || result.invalidMigrations.isEmpty()) {
      return false;
    }
    for (ValidateOutput output : result.invalidMigrations) {
      if (!REWRITTEN_MIGRATION_VERSION.equals(output.version)
          || output.errorDetails == null
          || output.errorDetails.errorCode != ErrorCode.CHECKSUM_MISMATCH) {
        return false;
      }
    }
    return true;
  }
}
