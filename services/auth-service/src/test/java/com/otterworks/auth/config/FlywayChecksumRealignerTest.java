package com.otterworks.auth.config;

import static org.assertj.core.api.Assertions.assertThat;

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

class FlywayChecksumRealignerTest {

  private static final String TABLE = "flyway_schema_history";
  private static final String SCHEMA = "public";

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
  void realignmentsMatchShippedMigrationChecksums() {
    Flyway flyway =
        Flyway.configure()
            .dataSource(dataSource)
            .locations("classpath:db/migration")
            .cleanDisabled(true)
            .load();

    for (FlywayChecksumRealigner.Realignment realignment : FlywayChecksumRealigner.REALIGNMENTS) {
      MigrationInfo resolved = null;
      for (MigrationInfo info : flyway.info().all()) {
        if (info.getVersion().getVersion().equals(realignment.version())) {
          resolved = info;
        }
      }
      assertThat(resolved).as("migration V%s", realignment.version()).isNotNull();
      assertThat(resolved.getChecksum()).isEqualTo(realignment.currentChecksum());
    }
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
