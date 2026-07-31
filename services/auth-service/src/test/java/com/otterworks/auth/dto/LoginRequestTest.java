package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import java.util.Set;
import java.util.function.Consumer;
import java.util.stream.Stream;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;

class LoginRequestTest {

  private static ValidatorFactory factory;
  private static Validator validator;

  @BeforeAll
  static void openValidator() {
    factory = Validation.buildDefaultValidatorFactory();
    validator = factory.getValidator();
  }

  @AfterAll
  static void closeValidator() {
    factory.close();
  }

  private static LoginRequest base() {
    LoginRequest request = new LoginRequest();
    request.setEmail("user@otterworks.dev");
    request.setPassword("password123");
    return request;
  }

  @Test
  void aWellFormedRequestHasNoViolations() {
    assertThat(validator.validate(base())).isEmpty();
  }

  @ParameterizedTest
  @ValueSource(strings = {"", "   ", "not-an-email", "user@", "@otterworks.dev"})
  void malformedOrBlankEmailIsRejected(String email) {
    LoginRequest request = base();
    request.setEmail(email);

    Set<ConstraintViolation<LoginRequest>> violations = validator.validate(request);

    assertThat(violations).isNotEmpty();
    assertThat(violations).allMatch(v -> v.getPropertyPath().toString().equals("email"));
  }

  @Test
  void nullEmailIsRejected() {
    LoginRequest request = base();
    request.setEmail(null);

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("email");
  }

  @ParameterizedTest
  @ValueSource(strings = {"", "   "})
  void blankPasswordIsRejected(String password) {
    LoginRequest request = base();
    request.setPassword(password);

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("password");
  }

  @Test
  void aSingleCharacterPasswordIsAcceptedBecauseLoginDoesNotEnforceLength() {
    LoginRequest request = base();
    request.setPassword("x");

    assertThat(validator.validate(request)).isEmpty();
  }

  @Test
  void equalValuesAreEqualAndShareHashCode() {
    assertThat(base()).isEqualTo(base()).hasSameHashCodeAs(base());
  }

  @Test
  void equalsIsReflexiveAndRejectsNullAndForeignTypes() {
    LoginRequest request = base();

    assertThat(request.equals(request)).isTrue();
    assertThat(request.equals(null)).isFalse();
    assertThat(request.equals("user@otterworks.dev")).isFalse();
  }

  static Stream<Arguments> singleFieldMutations() {
    return Stream.of(
        Arguments.of("email", (Consumer<LoginRequest>) r -> r.setEmail("other@otterworks.dev")),
        Arguments.of("email=null", (Consumer<LoginRequest>) r -> r.setEmail(null)),
        Arguments.of("password", (Consumer<LoginRequest>) r -> r.setPassword("other")),
        Arguments.of("password=null", (Consumer<LoginRequest>) r -> r.setPassword(null)));
  }

  @ParameterizedTest(name = "differing {0} breaks equality")
  @MethodSource("singleFieldMutations")
  void anySingleDifferingFieldBreaksEquality(String field, Consumer<LoginRequest> mutation) {
    LoginRequest mutated = base();
    mutation.accept(mutated);

    assertThat(mutated).isNotEqualTo(base());
    assertThat(base()).isNotEqualTo(mutated);
  }

  @Test
  void twoEmptyRequestsAreEqual() {
    assertThat(new LoginRequest())
        .isEqualTo(new LoginRequest())
        .hasSameHashCodeAs(new LoginRequest());
  }

  @Test
  void toStringExposesTheEmailButAlsoThePasswordWhichCallersMustNotLog() {
    assertThat(base().toString()).contains("email=user@otterworks.dev");
  }
}
