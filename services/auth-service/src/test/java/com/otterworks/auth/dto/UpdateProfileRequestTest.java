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

class UpdateProfileRequestTest {

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

  private static UpdateProfileRequest base() {
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("User One");
    request.setAvatarUrl("https://cdn/avatar.png");
    return request;
  }

  @Test
  void aWellFormedRequestHasNoViolations() {
    assertThat(validator.validate(base())).isEmpty();
  }

  @Test
  void anEmptyRequestIsValidBecauseEveryFieldIsOptional() {
    assertThat(validator.validate(new UpdateProfileRequest())).isEmpty();
  }

  @ParameterizedTest
  @ValueSource(ints = {1, 100})
  void displayNameAtTheLengthBoundariesIsAccepted(int length) {
    UpdateProfileRequest request = base();
    request.setDisplayName("n".repeat(length));

    assertThat(validator.validate(request)).isEmpty();
  }

  @Test
  void emptyDisplayNameIsRejectedByTheMinimumLength() {
    UpdateProfileRequest request = base();
    request.setDisplayName("");

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("displayName");
  }

  @Test
  void displayNameLongerThan100CharactersIsRejected() {
    UpdateProfileRequest request = base();
    request.setDisplayName("n".repeat(101));

    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("displayName");
  }

  @Test
  void avatarUrlOf500CharactersIsAcceptedAnd501IsRejected() {
    UpdateProfileRequest request = base();
    request.setAvatarUrl("u".repeat(500));
    assertThat(validator.validate(request)).isEmpty();

    request.setAvatarUrl("u".repeat(501));
    assertThat(validator.validate(request))
        .extracting(v -> v.getPropertyPath().toString())
        .containsExactly("avatarUrl");
  }

  @Test
  void equalValuesAreEqualAndShareHashCode() {
    assertThat(base()).isEqualTo(base()).hasSameHashCodeAs(base());
  }

  @Test
  void equalsIsReflexiveAndRejectsNullAndForeignTypes() {
    UpdateProfileRequest request = base();

    assertThat(request.equals(request)).isTrue();
    assertThat(request.equals(null)).isFalse();
    assertThat(request.equals("User One")).isFalse();
  }

  static Stream<Arguments> singleFieldMutations() {
    return Stream.of(
        Arguments.of("displayName", (Consumer<UpdateProfileRequest>) r -> r.setDisplayName("Two")),
        Arguments.of(
            "displayName=null", (Consumer<UpdateProfileRequest>) r -> r.setDisplayName(null)),
        Arguments.of(
            "avatarUrl", (Consumer<UpdateProfileRequest>) r -> r.setAvatarUrl("https://cdn/2.png")),
        Arguments.of("avatarUrl=null", (Consumer<UpdateProfileRequest>) r -> r.setAvatarUrl(null)));
  }

  @ParameterizedTest(name = "differing {0} breaks equality")
  @MethodSource("singleFieldMutations")
  void anySingleDifferingFieldBreaksEquality(
      String field, Consumer<UpdateProfileRequest> mutation) {
    UpdateProfileRequest mutated = base();
    mutation.accept(mutated);

    assertThat(mutated).isNotEqualTo(base());
    assertThat(base()).isNotEqualTo(mutated);
  }

  @Test
  void twoEmptyRequestsAreEqual() {
    assertThat(new UpdateProfileRequest())
        .isEqualTo(new UpdateProfileRequest())
        .hasSameHashCodeAs(new UpdateProfileRequest());
  }

  @Test
  void toStringExposesFieldValues() {
    assertThat(base().toString())
        .contains("displayName=User One")
        .contains("avatarUrl=https://cdn/avatar.png");
  }
}
