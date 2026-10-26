package com.otterworks.auth.config;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import javax.sql.DataSource;
import org.flywaydb.core.api.configuration.Configuration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.flyway.FlywayMigrationStrategy;
import org.springframework.context.annotation.Bean;

/**
 * V1 used to seed an admin account with a published password; the seed was removed from V1 and V5
 * disables the account on existing databases. Databases that applied the old V1 still record its
 * checksum, so it is realigned (only when it matches the old file exactly) before Flyway validates.
 */
@org.springframework.context.annotation.Configuration
public class FlywayConfig {

  private static final Logger log = LoggerFactory.getLogger(FlywayConfig.class);

  static final String V1_VERSION = "1";
  static final int LEGACY_V1_CHECKSUM = -1077113232;
  static final int CURRENT_V1_CHECKSUM = -1338442054;

  @Bean
  public FlywayMigrationStrategy flywayMigrationStrategy() {
    return flyway -> {
      realignLegacyV1Checksum(flyway.getConfiguration());
      flyway.migrate();
    };
  }

  static int realignLegacyV1Checksum(Configuration configuration) {
    DataSource dataSource = configuration.getDataSource();
    String table = qualifiedHistoryTable(configuration);
    try (Connection connection = dataSource.getConnection()) {
      if (!historyTableExists(connection, table)) {
        return 0;
      }
      try (PreparedStatement update =
          connection.prepareStatement(
              "UPDATE " + table + " SET checksum = ? WHERE version = ? AND checksum = ?")) {
        update.setInt(1, CURRENT_V1_CHECKSUM);
        update.setString(2, V1_VERSION);
        update.setInt(3, LEGACY_V1_CHECKSUM);
        int updated = update.executeUpdate();
        if (updated > 0) {
          log.info("Realigned checksum of migration V1 after removal of the seeded admin user");
        }
        return updated;
      }
    } catch (SQLException e) {
      throw new IllegalStateException("Could not realign Flyway checksum for V1", e);
    }
  }

  private static boolean historyTableExists(Connection connection, String table)
      throws SQLException {
    try (PreparedStatement check = connection.prepareStatement("SELECT to_regclass(?)")) {
      check.setString(1, table);
      try (ResultSet rs = check.executeQuery()) {
        return rs.next() && rs.getString(1) != null;
      }
    }
  }

  static String qualifiedHistoryTable(Configuration configuration) {
    String table = quote(configuration.getTable());
    String schema = configuration.getDefaultSchema();
    if (schema == null && configuration.getSchemas().length > 0) {
      schema = configuration.getSchemas()[0];
    }
    return schema == null ? table : quote(schema) + "." + table;
  }

  private static String quote(String identifier) {
    return "\"" + identifier.replace("\"", "\"\"") + "\"";
  }
}
