package com.otterworks.auth.config;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.zip.CRC32;
import org.junit.jupiter.api.Test;

class SeededAdminMigrationTest {

  private static String read(String path) throws IOException {
    try (InputStream in = SeededAdminMigrationTest.class.getResourceAsStream(path)) {
      assertThat(in).as(path).isNotNull();
      return new String(in.readAllBytes(), StandardCharsets.UTF_8);
    }
  }

  /** Same algorithm as Flyway's ChecksumCalculator: CRC32 over each line without its break. */
  private static int flywayChecksum(String path) throws IOException {
    CRC32 crc = new CRC32();
    try (BufferedReader reader =
        new BufferedReader(
            new InputStreamReader(
                SeededAdminMigrationTest.class.getResourceAsStream(path),
                StandardCharsets.UTF_8))) {
      String line;
      boolean first = true;
      while ((line = reader.readLine()) != null) {
        if (first && line.startsWith("\uFEFF")) {
          line = line.substring(1);
        }
        first = false;
        crc.update(line.getBytes(StandardCharsets.UTF_8));
      }
    }
    return (int) crc.getValue();
  }

  @Test
  void v1NoLongerSeedsAnyUser() throws IOException {
    String v1 = read("/db/migration/V1__create_users_table.sql");
    assertThat(v1).doesNotContainIgnoringCase("INSERT INTO");
    assertThat(v1).doesNotContain("admin@otterworks.dev");
  }

  @Test
  void realignedChecksumMatchesCurrentV1() throws IOException {
    assertThat(flywayChecksum("/db/migration/V1__create_users_table.sql"))
        .as("update FlywayConfig.CURRENT_V1_CHECKSUM when V1 changes")
        .isEqualTo(FlywayConfig.CURRENT_V1_CHECKSUM);
  }

  @Test
  void v5DisablesOnlyThePublishedSeedCredential() throws IOException {
    String v5 = read("/db/migration/V5__disable_seeded_admin.sql");
    assertThat(v5)
        .contains("a0000000-0000-0000-0000-000000000001")
        .contains("$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy")
        .contains("UPDATE refresh_tokens")
        .doesNotContainIgnoringCase("DELETE FROM users");
  }
}
