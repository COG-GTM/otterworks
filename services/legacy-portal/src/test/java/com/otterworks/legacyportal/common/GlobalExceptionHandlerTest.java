package com.otterworks.legacyportal.common;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import java.util.NoSuchElementException;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    void noSuchElementMapsTo404() {
        ResponseEntity<Map<String, String>> response =
                handler.handleNotFound(new NoSuchElementException("thing 7 not found"));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody())
                .containsExactly(
                        Map.entry("error", "Not Found"), Map.entry("message", "thing 7 not found"));
    }

    @Test
    void illegalArgumentMapsTo400() {
        ResponseEntity<Map<String, String>> response =
                handler.handleBadRequest(new IllegalArgumentException("rating must be between 1 and 5"));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody())
                .containsExactly(
                        Map.entry("error", "Bad Request"),
                        Map.entry("message", "rating must be between 1 and 5"));
    }
}
