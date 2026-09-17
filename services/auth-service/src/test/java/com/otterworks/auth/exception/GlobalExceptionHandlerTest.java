package com.otterworks.auth.exception;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.otterworks.auth.dto.RegisterRequest;
import io.jsonwebtoken.JwtException;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.validation.BeanPropertyBindingResult;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.MethodArgumentNotValidException;

class GlobalExceptionHandlerTest {

  private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

  @Test
  void illegalArgumentBecomes400WithItsMessage() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleIllegalArgument(new IllegalArgumentException("Email already registered"));

    assertBody(response, HttpStatus.BAD_REQUEST, "Email already registered");
  }

  @Test
  void validationErrorsAreJoinedIntoOneMessage() {
    BindingResult bindingResult =
        new BeanPropertyBindingResult(new RegisterRequest(), "registerRequest");
    bindingResult.rejectValue("email", "Email", "must be a well-formed email address");
    bindingResult.rejectValue("password", "Size", "size must be between 8 and 128");
    MethodArgumentNotValidException ex = mock(MethodArgumentNotValidException.class);
    when(ex.getBindingResult()).thenReturn(bindingResult);

    ResponseEntity<Map<String, Object>> response = handler.handleValidation(ex);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    assertThat(response.getBody()).isNotNull();
    assertThat((String) response.getBody().get("message"))
        .isEqualTo(
            "email: must be a well-formed email address, "
                + "password: size must be between 8 and 128");
  }

  @Test
  void jwtExceptionBecomes401WithoutLeakingDetails() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleJwtException(new JwtException("signature mismatch for key kid=abc"));

    assertBody(response, HttpStatus.UNAUTHORIZED, "Invalid or expired token");
    assertThat(response.getBody().get("message").toString()).doesNotContain("kid=abc");
  }

  @Test
  void accessDeniedBecomes403() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleAccessDenied(new AccessDeniedException("no ADMIN role"));

    assertBody(response, HttpStatus.FORBIDDEN, "Access denied");
  }

  @Test
  void unhandledExceptionBecomes500WithGenericMessage() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleGeneral(new IllegalStateException("connection pool exhausted"));

    assertBody(response, HttpStatus.INTERNAL_SERVER_ERROR, "Internal server error");
    assertThat(response.getBody().get("message").toString()).doesNotContain("connection pool");
  }

  private void assertBody(
      ResponseEntity<Map<String, Object>> response, HttpStatus status, String message) {
    assertThat(response.getStatusCode()).isEqualTo(status);
    Map<String, Object> body = response.getBody();
    assertThat(body).isNotNull();
    assertThat(body.get("status")).isEqualTo(status.value());
    assertThat(body.get("error")).isEqualTo(status.getReasonPhrase());
    assertThat(body.get("message")).isEqualTo(message);
    assertThat(Instant.parse(body.get("timestamp").toString())).isNotNull();
  }
}
