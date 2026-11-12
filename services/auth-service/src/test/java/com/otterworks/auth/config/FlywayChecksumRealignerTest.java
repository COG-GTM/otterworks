package com.otterworks.auth.config;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationInfo;
import org.h2.jdbcx.JdbcDataSource;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class FlywayChecksumRealignerTest {

  private static final String TABLE = "flyway_schema_history";
  private static final String SCHEMA = "public";

  private static final String CURRENT_ROLE_SEED =
      """
      INSERT INTO user_roles (user_id, role)
      SELECT u.id, r.role
      FROM users u
      CROSS JOIN (VALUES ('ADMIN'), ('USER')) AS r(role)
      WHERE u.email = 'admin@otterworks.dev';
      """;

  private static final String ORIGINAL_ROLE_SEED =
      """
      INSERT INTO user_roles (user_id, role) VALUES
      ('a0000000-0000-0000-0000-000000000001', 'ADMIN'),
      ('a0000000-0000-0000-0000-000000000001', 'USER');
      """;

  private JdbcDataSource dataSource;

  @BeforeEach
  void setUp() {
    dataSource = new JdbcDataSource();
    dataSource.setURL(
        "jdbc:h2:mem:"
            + UUID.randomUUID()
            + ";MODE=PostgreSQL;DB_CLOSE_DELAY=-1;DATABASE_TO_LOWER=TRUE");
    dataSource.setUser("sa");
  }

  @Test
  void currentChecksumMatchesShippedMigration() {
    assertThat(resolvedChecksum("classpath:db/migration", "1"))
        .isEqualTo(FlywayChecksumRealigner.REALIGNMENTS.get(0).currentChecksum());
  }

  @Test
  void previousChecksumMatchesOriginalMigrationText(@TempDir Path dir) throws IOException {
    String current;
    try (InputStream in =
        getClass().getResourceAsStream("/db/migration/V1__create_users_table.sql")) {
      current = new String(in.readAllBytes(), StandardCharsets.UTF_8);
    }
    assertThat(current).contains(CURRENT_ROLE_SEED);
    Files.writeString(
        dir.resolve("V1__create_users_table.sql"),
        current.replace(CURRENT_ROLE_SEED, ORIGINAL_ROLE_SEED));

    assertThat(resolvedChecksum("filesystem:" + dir, "1"))
        .isEqualTo(FlywayChecksumRealigner.REALIGNMENTS.get(0).previousChecksum());
  }

  @Test
  void updatesOnlyRowsWithThePreviousChecksum() throws SQLException {
    createHistory();
    insert("1", -1077113232);
    insert("2", -1077113232);

    int updated = FlywayChecksumRealigner.realign(dataSource, SCHEMA, TABLE);

    assertThat(updated).isEqualTo(1);
    assertThat(checksumOf("1")).isEqualTo(-1451564451);
    assertThat(checksumOf("2")).isEqualTo(-1077113232);
  }

  @Test
  void leavesUnknownChecksumsForFlywayValidationToReport() throws SQLException {
    createHistory();
    insert("1", 12345);

    assertThat(FlywayChecksumRealigner.realign(dataSource, SCHEMA, TABLE)).isZero();
    assertThat(checksumOf("1")).isEqualTo(12345);
  }

  @Test
  void isNoOpWhenHistoryTableIsMissing() throws SQLException {
    assertThat(FlywayChecksumRealigner.realign(dataSource, SCHEMA, TABLE)).isZero();
  }

  @Test
  void isIdempotent() throws SQLException {
    createHistory();
    insert("1", -1077113232);

    FlywayChecksumRealigner.realign(dataSource, SCHEMA, TABLE);

    assertThat(FlywayChecksumRealigner.realign(dataSource, SCHEMA, TABLE)).isZero();
    assertThat(checksumOf("1")).isEqualTo(-1451564451);
  }

  private Integer resolvedChecksum(String location, String version) {
    Flyway flyway =
        Flyway.configure().dataSource(dataSource).locations(location).cleanDisabled(true).load();
    for (MigrationInfo info : flyway.info().all()) {
      if (info.getVersion().getVersion().equals(version)) {
        return info.getChecksum();
      }
    }
    return null;
  }

  private void createHistory() throws SQLException {
    exec(
        "CREATE TABLE \"public\".\"flyway_schema_history\" ("
            + "installed_rank INT PRIMARY KEY, version VARCHAR(50), checksum INT)");
  }

  private void insert(String version, int checksum) throws SQLException {
    exec(
        "INSERT INTO \"public\".\"flyway_schema_history\" VALUES ("
            + version
            + ", '"
            + version
            + "', "
            + checksum
            + ")");
  }

  private Integer checksumOf(String version) throws SQLException {
    try (Connection connection = dataSource.getConnection();
        Statement statement = connection.createStatement();
        ResultSet rs =
            statement.executeQuery(
                "SELECT checksum FROM \"public\".\"flyway_schema_history\" WHERE version = '"
                    + version
                    + "'")) {
      return rs.next() ? rs.getInt(1) : null;
    }
  }

  private void exec(String sql) throws SQLException {
    try (Connection connection = dataSource.getConnection();
        Statement statement = connection.createStatement()) {
      statement.execute(sql);
    }
  }
}
