package com.otterworks.announcements;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.MountableFile;

/**
 * The {@code postgres} profile against PostgreSQL 15 initialised like the compose stack:
 * scripts/initdb.sh creates the announcements role and schema, the service connects as that role,
 * Flyway applies the migrations and Hibernate validates them.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("postgres")
@Testcontainers
class AnnouncementsPostgresIT {

    @Container
    static final PostgreSQLContainer<?> POSTGRES =
            new PostgreSQLContainer<>("postgres:15-alpine")
                    .withDatabaseName("legacyportal")
                    .withUsername("legacyportal")
                    .withPassword("legacyportal")
                    .withEnv("ANNOUNCEMENTS_DB_PASSWORD", "announcements-it")
                    .withCopyFileToContainer(
                            MountableFile.forHostPath("scripts/initdb.sh", 0755),
                            "/docker-entrypoint-initdb.d/announcements-service.sh");

    @DynamicPropertySource
    static void datasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", () -> "announcements");
        registry.add("spring.datasource.password", () -> "announcements-it");
    }

    @Autowired private MockMvc mockMvc;
    @Autowired private JdbcTemplate jdbc;

    @Test
    void migratesTheSchemaOwnedByTheServiceRole() {
        assertThat(jdbc.queryForObject("select current_user", String.class))
                .isEqualTo("announcements");
        assertThat(
                        jdbc.queryForObject(
                                "select schema_owner from information_schema.schemata"
                                        + " where schema_name = 'announcements'",
                                String.class))
                .isEqualTo("announcements");
        assertThat(
                        jdbc.queryForList(
                                "select version, success from announcements.flyway_schema_history"
                                        + " where version is not null order by installed_rank"))
                .containsExactly(Map.of("version", "1", "success", true));
    }

    @Test
    void columnsMatchTheRecordedMonolithDdl() {
        List<Map<String, Object>> columns =
                jdbc.queryForList(
                        "select column_name, data_type, character_maximum_length, is_nullable"
                                + " from information_schema.columns"
                                + " where table_schema = 'announcements' and table_name = 'announcement'"
                                + " order by column_name");

        assertThat(columns)
                .extracting(c -> c.get("column_name") + " " + c.get("data_type") + " "
                        + c.get("character_maximum_length") + " " + c.get("is_nullable"))
                .containsExactly(
                        "body character varying 4000 NO",
                        "created_at timestamp without time zone null NO",
                        "id bigint null NO",
                        "published boolean null NO",
                        "title character varying 200 NO");
        assertThat(
                        jdbc.queryForObject(
                                "select pg_get_serial_sequence('announcements.announcement', 'id')",
                                String.class))
                .isEqualTo("announcements.announcement_id_seq");
    }

    @Test
    void announcementsRoundTripOnPostgres() throws Exception {
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":\"Release\",\"body\":\"v1 is out\",\"published\":true}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").isNumber());

        mockMvc.perform(get("/api/announcements"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].title").value("Release"));
    }
}
