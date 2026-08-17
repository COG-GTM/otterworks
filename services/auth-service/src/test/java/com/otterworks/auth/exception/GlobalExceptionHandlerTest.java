package com.otterworks.auth.exception;

import static org.assertj.core.api.Assertions.assertThat;

import io.jsonwebtoken.JwtException;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.validation.BeanPropertyBindingResult;
import org.springframework.validation.BindingResult;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;

class GlobalExceptionHandlerTest {

  private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

  @Test
  void illegalArgumentBecomesBadRequestWithTheOriginalMessage() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleIllegalArgument(new IllegalArgumentException("Email already registered"));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    assertThat(response.getBody()).containsEntry("status", 400);
    assertThat(response.getBody()).containsEntry("error", "Bad Request");
    assertThat(response.getBody()).containsEntry("message", "Email already registered");
    assertThat(response.getBody().get("timestamp")).isInstanceOf(String.class);
  }

  @Test
  void validationErrorsAreJoinedIntoOneMessage() {
    BindingResult bindingResult = new BeanPropertyBindingResult(new Object(), "registerRequest");
    bindingResult.addError(new FieldError("registerRequest", "email", "must not be blank"));
    bindingResult.addError(new FieldError("registerRequest", "password", "size must be >= 8"));
    MethodArgumentNotValidException ex = new MethodArgumentNotValidException(null, bindingResult);

    ResponseEntity<Map<String, Object>> response = handler.handleValidation(ex);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    assertThat(response.getBody())
        .containsEntry("message", "email: must not be blank, password: size must be >= 8");
  }

  @Test
  void validationWithoutFieldErrorsYieldsAnEmptyMessage() {
    BindingResult bindingResult = new BeanPropertyBindingResult(new Object(), "loginRequest");
    MethodArgumentNotValidException ex = new MethodArgumentNotValidException(null, bindingResult);

    assertThat(handler.handleValidation(ex).getBody()).containsEntry("message", "");
  }

  @Test
  void jwtFailuresAreUnauthorizedAndDoNotLeakDetails() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleJwtException(new JwtException("signature mismatch for key kid=abc"));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    assertThat(response.getBody()).containsEntry("message", "Invalid or expired token");
  }

  @Test
  void accessDeniedIsForbidden() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleAccessDenied(new AccessDeniedException("no ROLE_ADMIN"));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
    assertThat(response.getBody()).containsEntry("message", "Access denied");
  }

  @Test
  void unexpectedFailuresAreGenericServerErrors() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleGeneral(new IllegalStateException("jdbc pool exhausted"));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
    assertThat(response.getBody()).containsEntry("message", "Internal server error");
    assertThat(response.getBody().values()).doesNotContain("jdbc pool exhausted");
  }
}
