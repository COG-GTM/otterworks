package com.otterworks.legacyportal.common;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.entry;

import java.util.NoSuchElementException;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    void missingEntityBecomesA404WithTheExceptionMessage() {
        assertThat(handler.handleNotFound(new NoSuchElementException("announcement 7 not found")))
                .satisfies(
                        response -> {
                            assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
                            assertThat(response.getBody())
                                    .containsExactly(
                                            entry("error", "Not Found"),
                                            entry("message", "announcement 7 not found"));
                        });
    }

    @Test
    void invalidArgumentBecomesA400WithTheExceptionMessage() {
        assertThat(
                        handler.handleBadRequest(
                                new IllegalArgumentException("rating must be between 1 and 5")))
                .satisfies(
                        response -> {
                            assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
                            assertThat(response.getBody())
                                    .containsExactly(
                                            entry("error", "Bad Request"),
                                            entry("message", "rating must be between 1 and 5"));
                        });
    }

    @Test
    void aMessagelessExceptionStillProducesAWellFormedBody() {
        assertThat(handler.handleBadRequest(new IllegalArgumentException()).getBody())
                .containsEntry("error", "Bad Request")
                .containsEntry("message", null);
    }
}
