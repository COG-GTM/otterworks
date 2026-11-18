package com.otterworks.auth.exception;

import static org.assertj.core.api.Assertions.*;

import io.jsonwebtoken.JwtException;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;

class GlobalExceptionHandlerTest {

  private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

  @Test
  void handleIllegalArgument_shouldReturn400WithMessage() {
    ResponseEntity<Map<String, Object>> res =
        handler.handleIllegalArgument(new IllegalArgumentException("bad"));

    assertThat(res.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    assertThat(res.getBody())
        .containsEntry("status", 400)
        .containsEntry("error", "Bad Request")
        .containsEntry("message", "bad")
        .containsKey("timestamp");
  }

  @Test
  void handleJwtException_shouldReturn401() {
    ResponseEntity<Map<String, Object>> res = handler.handleJwtException(new JwtException("x"));

    assertThat(res.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    assertThat(res.getBody()).containsEntry("message", "Invalid or expired token");
  }

  @Test
  void handleAccessDenied_shouldReturn403() {
    ResponseEntity<Map<String, Object>> res =
        handler.handleAccessDenied(new AccessDeniedException("nope"));

    assertThat(res.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
    assertThat(res.getBody()).containsEntry("message", "Access denied");
  }

  @Test
  void handleGeneral_shouldReturn500WithoutLeakingDetails() {
    ResponseEntity<Map<String, Object>> res =
        handler.handleGeneral(new RuntimeException("secret internals"));

    assertThat(res.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
    assertThat(res.getBody()).containsEntry("message", "Internal server error");
  }
}
