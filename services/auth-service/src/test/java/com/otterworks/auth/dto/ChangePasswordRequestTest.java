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

class ChangePasswordRequestTest {

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

  private static ChangePasswordRequest base() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("oldPassword");
    request.setNewPassword("newPassword123");
    return request;
  }

  @Test
  void aWellFormedRequestHasNoViolations() {
    assertThat(validator.validate(base())).isEmpty();
  }

  @ParameterizedTest
  @ValueSource(ints = {1, 7})
  void newPasswordShorterThanEightCharactersIsRejected(int length) {
    ChangePasswordRequest request = base();
    request.setNewPassword("a".repeat(length));

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("newPassword");
  }

  @ParameterizedTest
  @ValueSource(ints = {8, 128})
  void newPasswordAtTheLengthBoundariesIsAccepted(int length) {
    ChangePasswordRequest request = base();
    request.setNewPassword("a".repeat(length));

    assertThat(validator.validate(request)).isEmpty();
  }

  @Test
  void newPasswordLongerThan128CharactersIsRejected() {
    ChangePasswordRequest request = base();
    request.setNewPassword("a".repeat(129));

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("newPassword");
  }

  @Test
  void blankCurrentPasswordIsRejected() {
    ChangePasswordRequest request = base();
    request.setCurrentPassword("  ");

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("currentPassword");
  }

  @Test
  void anEmptyRequestReportsAViolationPerRequiredField() {
    assertThat(validator.validate(new ChangePasswordRequest()))
        .extracting(v -> v.getPropertyPath().toString())
        .contains("currentPassword", "newPassword");
  }

  @Test
  void equalValuesAreEqualAndShareHashCode() {
    assertThat(base()).isEqualTo(base()).hasSameHashCodeAs(base());
  }

  @Test
  void equalsIsReflexiveAndRejectsNullAndForeignTypes() {
    ChangePasswordRequest request = base();

    assertThat(request.equals(request)).isTrue();
    assertThat(request.equals(null)).isFalse();
    assertThat(request.equals("oldPassword")).isFalse();
  }

  static Stream<Arguments> singleFieldMutations() {
    return Stream.of(
        Arguments.of(
            "currentPassword", (Consumer<ChangePasswordRequest>) r -> r.setCurrentPassword("x")),
        Arguments.of(
            "currentPassword=null",
            (Consumer<ChangePasswordRequest>) r -> r.setCurrentPassword(null)),
        Arguments.of("newPassword", (Consumer<ChangePasswordRequest>) r -> r.setNewPassword("y")),
        Arguments.of(
            "newPassword=null", (Consumer<ChangePasswordRequest>) r -> r.setNewPassword(null)));
  }

  @ParameterizedTest(name = "differing {0} breaks equality")
  @MethodSource("singleFieldMutations")
  void anySingleDifferingFieldBreaksEquality(
      String field, Consumer<ChangePasswordRequest> mutation) {
    ChangePasswordRequest mutated = base();
    mutation.accept(mutated);

    assertThat(mutated).isNotEqualTo(base());
    assertThat(base()).isNotEqualTo(mutated);
  }

  @Test
  void twoEmptyRequestsAreEqual() {
    assertThat(new ChangePasswordRequest())
        .isEqualTo(new ChangePasswordRequest())
        .hasSameHashCodeAs(new ChangePasswordRequest());
  }

  @Test
  void gettersRoundTrip() {
    ChangePasswordRequest request = base();

    assertThat(request.getCurrentPassword()).isEqualTo("oldPassword");
    assertThat(request.getNewPassword()).isEqualTo("newPassword123");
  }
}
