package com.otterworks.portal.common.app;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

/** A service booted with portal-common: health, trailing-slash matching and the default error body. */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "spring.application.name=sample-service")
class PortalCommonServiceTest {

    @Autowired private TestRestTemplate rest;

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void healthReportsThisServicesName() {
        ResponseEntity<String> response = rest.getForEntity("/health", String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody()).isEqualTo("{\"status\":\"UP\",\"service\":\"sample-service\","
                + "\"banner\":\"OtterWorks Portal (on-prem) - contact portal-support@otterworks.example\"}");
    }

    @Test
    void trailingSlashMatchesTheMappedRoute() {
        ResponseEntity<String> response = rest.getForEntity("/api/samples/", String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody()).isEqualTo("page 1");
    }

    @Test
    void mvcErrorsRenderTheDefaultBodyWithoutDetails() throws Exception {
        ResponseEntity<String> response = rest.postForEntity("/api/samples", "{}", String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.METHOD_NOT_ALLOWED);
        assertThat(response.getHeaders().getContentType()).isEqualTo(MediaType.APPLICATION_JSON);
        JsonNode body = mapper.readTree(response.getBody());
        assertThat(body.fieldNames()).toIterable().containsExactly("timestamp", "status", "error", "path");
        assertThat(body.get("status").asInt()).isEqualTo(405);
        assertThat(body.get("error").asText()).isEqualTo("Method Not Allowed");
        assertThat(body.get("path").asText()).isEqualTo("/api/samples");
    }

    @Test
    void typeMismatchIsMappedThroughItsNumberFormatCause() {
        ResponseEntity<String> response = rest.getForEntity("/api/samples?page=abc", String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).isEqualTo("{\"error\":\"Bad Request\",\"message\":\"For input string: \\\"abc\\\"\"}");
    }

    @Test
    void unknownRouteRendersTheDefaultNotFoundBody() throws Exception {
        ResponseEntity<String> response = rest.getForEntity("/nope", String.class);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        JsonNode body = mapper.readTree(response.getBody());
        assertThat(body.fieldNames()).toIterable().containsExactly("timestamp", "status", "error", "path");
    }
}
