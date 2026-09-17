package com.otterworks.auth.exception;

import static org.assertj.core.api.Assertions.assertThat;

import io.jsonwebtoken.MalformedJwtException;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
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
  void illegalArgumentBecomesBadRequestCarryingTheOriginalMessage() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleIllegalArgument(new IllegalArgumentException("Email already registered"));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    assertThat(response.getBody())
        .containsEntry("status", 400)
        .containsEntry("error", "Bad Request")
        .containsEntry("message", "Email already registered");
    assertThat(Instant.parse((String) response.getBody().get("timestamp"))).isNotNull();
  }

  @Test
  void validationErrorsAreJoinedIntoASingleMessage() throws NoSuchMethodException {
    BindingResult bindingResult = new BeanPropertyBindingResult(new Object(), "registerRequest");
    bindingResult.addError(
        new FieldError("registerRequest", "email", "must be a well-formed email address"));
    bindingResult.addError(
        new FieldError("registerRequest", "password", "size must be between 8 and 128"));
    MethodParameter parameter =
        new MethodParameter(GlobalExceptionHandlerTest.class.getDeclaredMethod("target"), -1);

    ResponseEntity<Map<String, Object>> response =
        handler.handleValidation(new MethodArgumentNotValidException(parameter, bindingResult));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    assertThat(response.getBody().get("message"))
        .isEqualTo(
            "email: must be a well-formed email address, password: size must be between 8 and 128");
  }

  @Test
  void jwtFailuresAreMaskedAsUnauthorized() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleJwtException(new MalformedJwtException("signature mismatch on kid=abc"));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    assertThat(response.getBody())
        .containsEntry("status", 401)
        .containsEntry("message", "Invalid or expired token");
  }

  @Test
  void accessDeniedBecomesForbidden() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleAccessDenied(new AccessDeniedException("no ROLE_ADMIN"));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN);
    assertThat(response.getBody())
        .containsEntry("status", 403)
        .containsEntry("message", "Access denied");
  }

  @Test
  void unexpectedExceptionsAreMaskedAsInternalServerError() {
    ResponseEntity<Map<String, Object>> response =
        handler.handleGeneral(new IllegalStateException("jdbc pool exhausted"));

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
    assertThat(response.getBody())
        .containsEntry("status", 500)
        .containsEntry("error", "Internal Server Error")
        .containsEntry("message", "Internal server error");
  }

  @SuppressWarnings("unused")
  private void target() {
    // Signature holder for the MethodParameter required by MethodArgumentNotValidException.
  }
}
