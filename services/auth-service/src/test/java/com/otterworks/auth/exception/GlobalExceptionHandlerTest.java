package com.otterworks.auth.exception;

import static org.assertj.core.api.Assertions.*;

import io.jsonwebtoken.MalformedJwtException;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;

class GlobalExceptionHandlerTest {

  private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

  @Test
  void illegalArgumentMapsTo400WithMessage() {
    ResponseEntity<Map<String, Object>> res =
        handler.handleIllegalArgument(new IllegalArgumentException("Email already registered"));

    assertThat(res.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    assertThat(res.getBody())
        .containsEntry("status", 400)
        .containsEntry("message", "Email already registered")
        .containsKey("timestamp");
  }

  @Test
  void jwtExceptionMapsTo401WithoutLeakingDetail() {
    ResponseEntity<Map<String, Object>> res =
        handler.handleJwtException(new MalformedJwtException("secret internals"));

    assertThat(res.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    assertThat(res.getBody()).containsEntry("message", "Invalid or expired token");
  }

  @Test
  void accessDeniedMapsTo403() {
    ResponseEntity<Map<String, Object>> res =
        handler.handleAccessDenied(new AccessDeniedException("nope"));

    assertThat(res.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
    assertThat(res.getBody()).containsEntry("error", "Forbidden");
  }

  @Test
  void unexpectedExceptionMapsTo500WithGenericMessage() {
    ResponseEntity<Map<String, Object>> res =
        handler.handleGeneral(new RuntimeException("db password=hunter2"));

    assertThat(res.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
    assertThat(res.getBody().get("message")).isEqualTo("Internal server error");
    assertThat(res.getBody().toString()).doesNotContain("hunter2");
  }
}
