package com.otterworks.auth.exception;

import static org.assertj.core.api.Assertions.*;

import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

class GlobalExceptionHandlerTest {

  private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

  @Test
  void badRequestException_returnsItsClientMessage() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleBadRequest(new BadRequestException("Invalid credentials"));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    assertThat(response.getBody()).containsEntry("message", "Invalid credentials");
  }

  @Test
  void otherIllegalArgumentException_returnsGenericMessage() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleIllegalArgument(
            new IllegalArgumentException("Invalid UUID string: alice@example.com"));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    assertThat(response.getBody()).containsEntry("message", "Invalid request");
  }
}
