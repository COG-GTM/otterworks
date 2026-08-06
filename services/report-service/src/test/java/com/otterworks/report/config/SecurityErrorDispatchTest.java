package com.otterworks.report.config;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.TestPropertySource;

import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.notNullValue;

/**
 * Guards the error dispatch against Spring Security 6's deny-by-default behaviour.
 *
 * These run over a real servlet container because MockMvc never performs the
 * container's ERROR dispatch. Without a terminal rule in {@link SecurityConfig},
 * every one of these paths returns a bodyless 403 while the MockMvc suite stays green.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
@TestPropertySource(properties =
        "spring.datasource.url=jdbc:h2:mem:securityerrordispatch;DB_CLOSE_DELAY=-1")
public class SecurityErrorDispatchTest {

    @Autowired
    private TestRestTemplate restTemplate;

    @Test
    public void unmappedPathReturns404NotForbidden() {
        ResponseEntity<String> response = restTemplate.getForEntity("/nonexistent-path", String.class);

        assertThat(response.getStatusCode(), is(HttpStatus.NOT_FOUND));
        assertThat(response.getBody(), is(notNullValue()));
    }

    @Test
    public void invalidPathVariableReturns400NotForbidden() {
        ResponseEntity<String> response = restTemplate.getForEntity("/api/v1/reports/abc", String.class);

        assertThat(response.getStatusCode(), is(HttpStatus.BAD_REQUEST));
        assertThat(response.getBody(), is(notNullValue()));
    }

    @Test
    public void wrongMethodReturns405NotForbidden() {
        ResponseEntity<String> response = restTemplate.exchange(
                "/api/v1/reports", HttpMethod.PUT, null, String.class);

        assertThat(response.getStatusCode(), is(HttpStatus.METHOD_NOT_ALLOWED));
    }
}
