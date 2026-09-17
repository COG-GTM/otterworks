package com.otterworks.auth.exception;

import static org.assertj.core.api.Assertions.assertThat;

import io.jsonwebtoken.JwtException;
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

  private static void assertEnvelope(
      ResponseEntity<Map<String, Object>> response, HttpStatus status, String message) {
    assertThat(response.getStatusCode()).isEqualTo(status);
    Map<String, Object> body = response.getBody();
    assertThat(body).isNotNull();
    assertThat(body.get("status")).isEqualTo(status.value());
    assertThat(body.get("error")).isEqualTo(status.getReasonPhrase());
    assertThat(body.get("message")).isEqualTo(message);
    assertThat(Instant.parse((String) body.get("timestamp"))).isNotNull();
    assertThat(body.keySet()).containsExactly("timestamp", "status", "error", "message");
  }

  @Test
  void illegalArgumentBecomesA400CarryingTheOriginalMessage() {
    assertEnvelope(
        handler.handleIllegalArgument(new IllegalArgumentException("Email already registered")),
        HttpStatus.BAD_REQUEST,
        "Email already registered");
  }

  private static MethodArgumentNotValidException validationFailure(BindingResult bindingResult)
      throws NoSuchMethodException {
    return new MethodArgumentNotValidException(
        new MethodParameter(
            GlobalExceptionHandlerTest.class.getDeclaredMethod("target", String.class), 0),
        bindingResult);
  }

  @Test
  void validationFailuresAreJoinedIntoOneFieldByFieldMessage() throws NoSuchMethodException {
    BindingResult bindingResult = new BeanPropertyBindingResult(new Object(), "registerRequest");
    bindingResult.addError(
        new FieldError("registerRequest", "email", "must be a well-formed email address"));
    bindingResult.addError(
        new FieldError("registerRequest", "password", "size must be between 8 and 128"));

    ResponseEntity<Map<String, Object>> response =
        handler.handleValidation(validationFailure(bindingResult));

    assertEnvelope(
        response,
        HttpStatus.BAD_REQUEST,
        "email: must be a well-formed email address, password: size must be between 8 and 128");
  }

  @Test
  void aValidationFailureWithNoFieldErrorsYieldsAnEmptyMessage() throws NoSuchMethodException {
    BindingResult bindingResult = new BeanPropertyBindingResult(new Object(), "registerRequest");

    assertEnvelope(
        handler.handleValidation(validationFailure(bindingResult)), HttpStatus.BAD_REQUEST, "");
  }

  @Test
  void jwtFailuresBecomeA401WithoutLeakingTheParserDetail() {
    assertEnvelope(
        handler.handleJwtException(new JwtException("JWT signature does not match secret abc")),
        HttpStatus.UNAUTHORIZED,
        "Invalid or expired token");
  }

  @Test
  void accessDeniedBecomesA403WithAGenericMessage() {
    assertEnvelope(
        handler.handleAccessDenied(new AccessDeniedException("Access is denied to /api/v1/users")),
        HttpStatus.FORBIDDEN,
        "Access denied");
  }

  @Test
  void anyOtherExceptionBecomesA500WithoutLeakingTheCause() {
    assertEnvelope(
        handler.handleGeneral(new IllegalStateException("connection pool exhausted")),
        HttpStatus.INTERNAL_SERVER_ERROR,
        "Internal server error");
  }

  @SuppressWarnings("unused")
  private void target(String argument) {
    // Signature-only method: MethodArgumentNotValidException needs a MethodParameter.
  }
}
