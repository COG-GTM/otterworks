package com.otterworks.legacyportal.common;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.NoSuchElementException;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    void missingResourceBecomesNotFound() {
        ResponseEntity<Map<String, String>> response =
                handler.handleNotFound(new NoSuchElementException("announcement 9 not found"));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody())
                .containsEntry("error", "Not Found")
                .containsEntry("message", "announcement 9 not found");
    }

    @Test
    void invalidArgumentBecomesBadRequest() {
        ResponseEntity<Map<String, String>> response =
                handler.handleBadRequest(new IllegalArgumentException("rating must be 1..5"));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody())
                .containsEntry("error", "Bad Request")
                .containsEntry("message", "rating must be 1..5");
    }

    @Test
    void exceptionsWithoutAMessageStillProduceABody() {
        ResponseEntity<Map<String, String>> response =
                handler.handleNotFound(new NoSuchElementException());

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody()).containsEntry("error", "Not Found");
    }
}
