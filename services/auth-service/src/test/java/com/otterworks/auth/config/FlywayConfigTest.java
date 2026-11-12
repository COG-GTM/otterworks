package com.otterworks.auth.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationInfo;
import org.flywaydb.core.api.MigrationInfoService;
import org.flywaydb.core.api.MigrationVersion;
import org.flywaydb.core.api.configuration.Configuration;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

class FlywayConfigTest {

  private JdbcTemplate jdbcTemplate;
  private Flyway flyway;
  private MigrationInfoService infoService;

  @BeforeEach
  void setUp() {
    DriverManagerDataSource dataSource =
        new DriverManagerDataSource(
            "jdbc:h2:mem:flywaycfg;MODE=PostgreSQL;DB_CLOSE_DELAY=-1;DATABASE_TO_LOWER=TRUE",
            "sa",
            "");
    jdbcTemplate = new JdbcTemplate(dataSource);
    jdbcTemplate.execute("DROP TABLE IF EXISTS flyway_schema_history");
    jdbcTemplate.execute("CREATE TABLE flyway_schema_history (version VARCHAR(50), checksum INT)");

    Configuration configuration = mock(Configuration.class);
    when(configuration.getDataSource()).thenReturn(dataSource);
    when(configuration.getTable()).thenReturn("flyway_schema_history");

    infoService = mock(MigrationInfoService.class);
    flyway = mock(Flyway.class);
    when(flyway.getConfiguration()).thenReturn(configuration);
    when(flyway.info()).thenReturn(infoService);
  }

  @Test
  void realign_whenLegacyV1Applied_shouldUpdateOnlyV1Checksum() {
    insertHistory("1", FlywayConfig.LEGACY_V1_CHECKSUM);
    insertHistory("2", 42);
    stubApplied(migration("1", FlywayConfig.LEGACY_V1_CHECKSUM), migration("2", 42));

    FlywayConfig.realignLegacyV1Checksum(flyway);

    assertThat(checksum("1")).isEqualTo(FlywayConfig.CURRENT_V1_CHECKSUM);
    assertThat(checksum("2")).isEqualTo(42);
  }

  @Test
  void realign_whenV1AlreadyCurrent_shouldLeaveHistoryUntouched() {
    insertHistory("1", FlywayConfig.CURRENT_V1_CHECKSUM);
    stubApplied(migration("1", FlywayConfig.CURRENT_V1_CHECKSUM));

    FlywayConfig.realignLegacyV1Checksum(flyway);

    assertThat(checksum("1")).isEqualTo(FlywayConfig.CURRENT_V1_CHECKSUM);
  }

  @Test
  void realign_whenV1DriftedToUnknownChecksum_shouldNotMaskIt() {
    insertHistory("1", 12345);
    stubApplied(migration("1", 12345));

    FlywayConfig.realignLegacyV1Checksum(flyway);

    assertThat(checksum("1")).isEqualTo(12345);
  }

  private void stubApplied(MigrationInfo... applied) {
    when(infoService.applied()).thenReturn(applied);
  }

  private void insertHistory(String version, int checksum) {
    jdbcTemplate.update(
        "INSERT INTO flyway_schema_history (version, checksum) VALUES (?, ?)", version, checksum);
  }

  private Integer checksum(String version) {
    return jdbcTemplate.queryForObject(
        "SELECT checksum FROM flyway_schema_history WHERE version = ?", Integer.class, version);
  }

  private static MigrationInfo migration(String version, int checksum) {
    MigrationInfo info = mock(MigrationInfo.class);
    when(info.getVersion()).thenReturn(MigrationVersion.fromVersion(version));
    when(info.getChecksum()).thenReturn(checksum);
    return info;
  }
}
