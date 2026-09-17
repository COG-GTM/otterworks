package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import java.util.function.Consumer;
import java.util.stream.Stream;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;

class RegisterRequestTest {

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

  private static RegisterRequest base() {
    RegisterRequest request = new RegisterRequest();
    request.setEmail("user@otterworks.dev");
    request.setPassword("password123");
    request.setDisplayName("User One");
    return request;
  }

  @Test
  void aWellFormedRequestHasNoViolations() {
    assertThat(validator.validate(base())).isEmpty();
  }

  @ParameterizedTest
  @ValueSource(ints = {1, 7})
  void passwordShorterThanEightCharactersIsRejected(int length) {
    RegisterRequest request = base();
    request.setPassword("a".repeat(length));

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("password");
  }

  @ParameterizedTest
  @ValueSource(ints = {8, 128})
  void passwordAtTheLengthBoundariesIsAccepted(int length) {
    RegisterRequest request = base();
    request.setPassword("a".repeat(length));

    assertThat(validator.validate(request)).isEmpty();
  }

  @Test
  void passwordLongerThan128CharactersIsRejected() {
    RegisterRequest request = base();
    request.setPassword("a".repeat(129));

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("password");
  }

  @ParameterizedTest
  @ValueSource(ints = {1, 100})
  void displayNameAtTheLengthBoundariesIsAccepted(int length) {
    RegisterRequest request = base();
    request.setDisplayName("n".repeat(length));

    assertThat(validator.validate(request)).isEmpty();
  }

  @Test
  void displayNameLongerThan100CharactersIsRejected() {
    RegisterRequest request = base();
    request.setDisplayName("n".repeat(101));

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("displayName");
  }

  @Test
  void unicodeDisplayNameIsAccepted() {
    RegisterRequest request = base();
    request.setDisplayName("水獭工房 🦦");

    assertThat(validator.validate(request)).isEmpty();
  }

  @Test
  void blankDisplayNameIsRejected() {
    RegisterRequest request = base();
    request.setDisplayName("   ");

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("displayName");
  }

  @Test
  void anEmptyRequestReportsOneViolationPerRequiredField() {
    assertThat(validator.validate(new RegisterRequest()))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactlyInAnyOrder("email", "password", "displayName");
  }

  @ParameterizedTest
  @ValueSource(strings = {"not-an-email", "user@", "@otterworks.dev"})
  void malformedEmailIsRejected(String email) {
    RegisterRequest request = base();
    request.setEmail(email);

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("email");
  }

  @Test
  void equalValuesAreEqualAndShareHashCode() {
    assertThat(base()).isEqualTo(base()).hasSameHashCodeAs(base());
  }

  @Test
  void equalsIsReflexiveAndRejectsNullAndForeignTypes() {
    RegisterRequest request = base();

    assertThat(request.equals(request)).isTrue();
    assertThat(request.equals(null)).isFalse();
    assertThat(request.equals("user@otterworks.dev")).isFalse();
  }

  static Stream<Arguments> singleFieldMutations() {
    return Stream.of(
        Arguments.of("email", (Consumer<RegisterRequest>) r -> r.setEmail("other@otterworks.dev")),
        Arguments.of("email=null", (Consumer<RegisterRequest>) r -> r.setEmail(null)),
        Arguments.of("password", (Consumer<RegisterRequest>) r -> r.setPassword("otherpassword")),
        Arguments.of("password=null", (Consumer<RegisterRequest>) r -> r.setPassword(null)),
        Arguments.of("displayName", (Consumer<RegisterRequest>) r -> r.setDisplayName("Other")),
        Arguments.of("displayName=null", (Consumer<RegisterRequest>) r -> r.setDisplayName(null)));
  }

  @ParameterizedTest(name = "differing {0} breaks equality")
  @MethodSource("singleFieldMutations")
  void anySingleDifferingFieldBreaksEquality(String field, Consumer<RegisterRequest> mutation) {
    RegisterRequest mutated = base();
    mutation.accept(mutated);

    assertThat(mutated).isNotEqualTo(base());
    assertThat(base()).isNotEqualTo(mutated);
  }

  @Test
  void twoEmptyRequestsAreEqual() {
    assertThat(new RegisterRequest())
        .isEqualTo(new RegisterRequest())
        .hasSameHashCodeAs(new RegisterRequest());
  }

  @Test
  void toStringExposesTheDisplayName() {
    assertThat(base().toString()).contains("displayName=User One");
  }
}
