package com.otterworks.servicetemplate;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ServiceTemplateApplicationTest {

    @Container @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:15-alpine");

    @Autowired private TestRestTemplate http;

    @Autowired private JdbcTemplate jdbc;

    @Test
    void livenessAndReadinessProbesAreUp() {
        for (String path :
                List.of("/actuator/health/liveness", "/actuator/health/readiness", "/livez", "/readyz")) {
            ResponseEntity<Map> response = http.getForEntity(path, Map.class);
            assertThat(response.getStatusCode()).as(path).isEqualTo(HttpStatus.OK);
            assertThat(response.getBody()).as(path).containsEntry("status", "UP");
        }
    }

    @Test
    void flywayMigratesIntoTheServiceSchema() {
        List<String> applied =
                jdbc.queryForList(
                        "SELECT version FROM service_template.flyway_schema_history"
                                + " WHERE success AND type = 'SQL' ORDER BY installed_rank",
                        String.class);
        assertThat(applied).containsExactly("1");
        String table =
                jdbc.queryForObject(
                        "SELECT table_name FROM information_schema.tables"
                                + " WHERE table_schema = 'service_template' AND table_name = 'example_items'",
                        String.class);
        assertThat(table).isEqualTo("example_items");
    }

    @Test
    void exampleItemsRoundTripThroughJpa() {
        ResponseEntity<Map> created =
                http.postForEntity("/api/example-items", Map.of("name", "first"), Map.class);
        assertThat(created.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(created.getBody()).containsEntry("name", "first").containsKey("id");

        ResponseEntity<List<Map<String, Object>>> listed =
                http.exchange(
                        "/api/example-items",
                        HttpMethod.GET,
                        null,
                        new ParameterizedTypeReference<>() {});
        assertThat(listed.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(listed.getBody()).extracting(item -> item.get("name")).contains("first");
    }

    @Test
    void invalidRequestIsRejected() {
        ResponseEntity<Map> response =
                http.postForEntity("/api/example-items", Map.of("name", " "), Map.class);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }
}
