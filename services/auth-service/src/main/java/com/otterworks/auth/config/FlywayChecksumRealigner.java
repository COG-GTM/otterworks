package com.otterworks.auth.config;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import javax.sql.DataSource;
import lombok.extern.slf4j.Slf4j;
import org.flywaydb.core.api.configuration.Configuration;

/**
 * Updates schema-history checksums for migrations whose SQL was edited without changing what they
 * create, so databases that already applied the previous text still pass Flyway validation. Only
 * rows that carry the exact previous checksum are touched.
 */
@Slf4j
public final class FlywayChecksumRealigner {

  record Realignment(String version, int previousChecksum, int currentChecksum) {}

  static final List<Realignment> REALIGNMENTS =
      List.of(new Realignment("1", -1077113232, -1451564451));

  private FlywayChecksumRealigner() {}

  public static int realign(Configuration configuration) throws SQLException {
    return realign(
        configuration.getDataSource(), schemaOf(configuration), configuration.getTable());
  }

  static int realign(DataSource dataSource, String schema, String table) throws SQLException {
    try (Connection connection = dataSource.getConnection()) {
      String effectiveSchema = schema != null ? schema : connection.getSchema();
      if (!tableExists(connection, effectiveSchema, table)) {
        return 0;
      }
      String sql =
          "UPDATE "
              + quote(effectiveSchema)
              + "."
              + quote(table)
              + " SET checksum = ? WHERE version = ? AND checksum = ?";
      int updated = 0;
      try (PreparedStatement statement = connection.prepareStatement(sql)) {
        for (Realignment realignment : REALIGNMENTS) {
          statement.setInt(1, realignment.currentChecksum());
          statement.setString(2, realignment.version());
          statement.setInt(3, realignment.previousChecksum());
          int rows = statement.executeUpdate();
          if (rows > 0) {
            log.info(
                "Realigned Flyway checksum of migration V{} ({} -> {})",
                realignment.version(),
                realignment.previousChecksum(),
                realignment.currentChecksum());
          }
          updated += rows;
        }
      }
      return updated;
    }
  }

  private static String schemaOf(Configuration configuration) {
    if (configuration.getDefaultSchema() != null) {
      return configuration.getDefaultSchema();
    }
    String[] schemas = configuration.getSchemas();
    return schemas.length > 0 ? schemas[0] : null;
  }

  private static boolean tableExists(Connection connection, String schema, String table)
      throws SQLException {
    try (ResultSet tables =
        connection.getMetaData().getTables(connection.getCatalog(), schema, table, null)) {
      return tables.next();
    }
  }

  private static String quote(String identifier) {
    return "\"" + identifier.replace("\"", "\"\"") + "\"";
  }
}
