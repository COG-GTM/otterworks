package com.otterworks.preferences;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
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
 * scripts/initdb.sh creates the preferences role and the user_preferences schema, the service
 * connects as that role, Flyway applies the migrations and Hibernate validates them.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("postgres")
@Testcontainers
class PreferencesPostgresIT {

    @Container
    static final PostgreSQLContainer<?> POSTGRES =
            new PostgreSQLContainer<>("postgres:15-alpine")
                    .withDatabaseName("legacyportal")
                    .withUsername("legacyportal")
                    .withPassword("legacyportal")
                    .withEnv("PREFERENCES_DB_PASSWORD", "preferences-it")
                    .withCopyFileToContainer(
                            MountableFile.forHostPath("scripts/initdb.sh", 0755),
                            "/docker-entrypoint-initdb.d/preferences-service.sh");

    @DynamicPropertySource
    static void datasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", () -> "preferences");
        registry.add("spring.datasource.password", () -> "preferences-it");
    }

    @Autowired private MockMvc mockMvc;
    @Autowired private JdbcTemplate jdbc;

    @Test
    void migratesTheSchemaOwnedByTheServiceRole() {
        assertThat(jdbc.queryForObject("select current_user", String.class))
                .isEqualTo("preferences");
        assertThat(
                        jdbc.queryForObject(
                                "select schema_owner from information_schema.schemata"
                                        + " where schema_name = 'user_preferences'",
                                String.class))
                .isEqualTo("preferences");
        assertThat(
                        jdbc.queryForList(
                                "select version, success from user_preferences.flyway_schema_history"
                                        + " where version is not null order by installed_rank"))
                .containsExactly(Map.of("version", "1", "success", true));
    }

    @Test
    void columnsMatchTheRecordedMonolithDdl() {
        List<Map<String, Object>> columns =
                jdbc.queryForList(
                        "select column_name, data_type, character_maximum_length, is_nullable"
                                + " from information_schema.columns"
                                + " where table_schema = 'user_preferences' and table_name = 'user_preference'"
                                + " order by column_name");

        assertThat(columns)
                .extracting(c -> c.get("column_name") + " " + c.get("data_type") + " "
                        + c.get("character_maximum_length") + " " + c.get("is_nullable"))
                .containsExactly(
                        "email_notifications boolean null NO",
                        "locale character varying 20 NO",
                        "theme character varying 20 NO",
                        "user_id character varying 100 NO");
        assertThat(
                        jdbc.queryForList(
                                "select kcu.column_name from information_schema.table_constraints tc"
                                        + " join information_schema.key_column_usage kcu"
                                        + " on tc.constraint_name = kcu.constraint_name"
                                        + " and tc.table_schema = kcu.table_schema"
                                        + " where tc.table_schema = 'user_preferences'"
                                        + " and tc.table_name = 'user_preference'"
                                        + " and tc.constraint_type = 'PRIMARY KEY'",
                                String.class))
                .containsExactly("user_id");
    }

    @Test
    void preferencesRoundTripOnPostgres() throws Exception {
        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"theme\":\"dark\",\"locale\":\"nl-NL\",\"emailNotifications\":false}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("u1"));

        mockMvc.perform(get("/api/preferences/u1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.locale").value("nl-NL"))
                .andExpect(jsonPath("$.emailNotifications").value(false));
    }
}
