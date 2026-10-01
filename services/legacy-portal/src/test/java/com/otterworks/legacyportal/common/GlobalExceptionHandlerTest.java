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
    void missingEntityBecomesNotFoundWithTheOriginalMessage() {
        ResponseEntity<Map<String, String>> response =
                handler.handleNotFound(new NoSuchElementException("announcement 42 not found"));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody())
                .containsEntry("error", "Not Found")
                .containsEntry("message", "announcement 42 not found");
    }

    @Test
    void invalidArgumentBecomesBadRequestWithTheOriginalMessage() {
        ResponseEntity<Map<String, String>> response =
                handler.handleBadRequest(new IllegalArgumentException("rating must be between 1 and 5"));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody())
                .containsEntry("error", "Bad Request")
                .containsEntry("message", "rating must be between 1 and 5");
    }

    @Test
    void bodyKeysAreOrderedErrorThenMessage() {
        Map<String, String> body =
                handler.handleBadRequest(new IllegalArgumentException("boom")).getBody();

        assertThat(body).containsExactly(
                org.assertj.core.data.MapEntry.entry("error", "Bad Request"),
                org.assertj.core.data.MapEntry.entry("message", "boom"));
    }

    @Test
    void nullExceptionMessageIsPassedThroughAsNull() {
        ResponseEntity<Map<String, String>> response =
                handler.handleNotFound(new NoSuchElementException());

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody()).containsEntry("message", null);
    }
}
