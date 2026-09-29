package com.otterworks.feedback;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
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
 * scripts/initdb.sh creates the feedback role and schema, the service connects as that role,
 * Flyway applies the migrations and Hibernate validates them.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("postgres")
@Testcontainers
class FeedbackPostgresIT {

    @Container
    static final PostgreSQLContainer<?> POSTGRES =
            new PostgreSQLContainer<>("postgres:15-alpine")
                    .withDatabaseName("legacyportal")
                    .withUsername("legacyportal")
                    .withPassword("legacyportal")
                    .withEnv("FEEDBACK_DB_PASSWORD", "feedback-it")
                    .withCopyFileToContainer(
                            MountableFile.forHostPath("scripts/initdb.sh", 0755),
                            "/docker-entrypoint-initdb.d/feedback-service.sh");

    @DynamicPropertySource
    static void datasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", () -> "feedback");
        registry.add("spring.datasource.password", () -> "feedback-it");
    }

    @Autowired private MockMvc mockMvc;
    @Autowired private JdbcTemplate jdbc;

    @Test
    void migratesTheSchemaOwnedByTheServiceRole() {
        assertThat(jdbc.queryForObject("select current_user", String.class))
                .isEqualTo("feedback");
        assertThat(
                        jdbc.queryForObject(
                                "select schema_owner from information_schema.schemata"
                                        + " where schema_name = 'feedback'",
                                String.class))
                .isEqualTo("feedback");
        assertThat(
                        jdbc.queryForList(
                                "select version, success from feedback.flyway_schema_history"
                                        + " where version is not null order by installed_rank"))
                .containsExactly(Map.of("version", "1", "success", true));
    }

    @Test
    void columnsMatchTheRecordedMonolithDdl() {
        List<Map<String, Object>> columns =
                jdbc.queryForList(
                        "select column_name, data_type, character_maximum_length, is_nullable"
                                + " from information_schema.columns"
                                + " where table_schema = 'feedback' and table_name = 'feedback'"
                                + " order by column_name");

        assertThat(columns)
                .extracting(c -> c.get("column_name") + " " + c.get("data_type") + " "
                        + c.get("character_maximum_length") + " " + c.get("is_nullable"))
                .containsExactly(
                        "created_at timestamp without time zone null NO",
                        "id bigint null NO",
                        "message character varying 2000 NO",
                        "rating integer null NO",
                        "user_id character varying 100 NO");
        assertThat(
                        jdbc.queryForObject(
                                "select pg_get_serial_sequence('feedback.feedback', 'id')",
                                String.class))
                .isEqualTo("feedback.feedback_id_seq");
    }

    @Test
    void feedbackRoundTripAndAverageOnPostgres() throws Exception {
        mockMvc.perform(get("/api/feedback/average-rating"))
                .andExpect(status().isOk())
                .andExpect(content().json("{\"averageRating\":0.0}", true));

        for (int rating : new int[] {5, 4, 4}) {
            mockMvc.perform(
                            post("/api/feedback")
                                    .contentType(MediaType.APPLICATION_JSON)
                                    .content("{\"userId\":\"u1\",\"rating\":" + rating
                                            + ",\"message\":\"m\"}"))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.id").isNumber());
        }

        mockMvc.perform(get("/api/feedback").param("userId", "u1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(3));
        mockMvc.perform(get("/api/feedback/average-rating"))
                .andExpect(status().isOk())
                .andExpect(content().string("{\"averageRating\":4.333333333333333}"));
    }
}
