package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import java.util.function.Consumer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

/** Bean-validation rules and value semantics of the inbound request DTOs. */
class RequestDtoTest {

  private static ValidatorFactory factory;
  private static Validator validator;

  @BeforeAll
  static void startValidator() {
    factory = Validation.buildDefaultValidatorFactory();
    validator = factory.getValidator();
  }

  @AfterAll
  static void stopValidator() {
    factory.close();
  }

  @Test
  void registerRequestAcceptsAValidPayload() {
    assertThat(validator.validate(registerRequest())).isEmpty();
  }

  @ParameterizedTest
  @CsvSource({
    "not-an-email, password123, Name, email",
    "'', password123, Name, email",
    "user@otterworks.dev, short, Name, password",
    "user@otterworks.dev, '', Name, password",
    "user@otterworks.dev, password123, '', displayName"
  })
  void registerRequestRejectsInvalidFields(
      String email, String password, String displayName, String expectedField) {
    RegisterRequest request = new RegisterRequest();
    request.setEmail(email);
    request.setPassword(password);
    request.setDisplayName(displayName);

    assertThat(validator.validate(request))
        .isNotEmpty()
        .anySatisfy(v -> assertThat(v.getPropertyPath()).hasToString(expectedField));
  }

  @Test
  void registerRequestRejectsAnOverlongDisplayName() {
    RegisterRequest request = registerRequest();
    request.setDisplayName("x".repeat(101));

    assertThat(validator.validate(request)).isNotEmpty();
  }

  @Test
  void registerRequestValueSemantics() {
    assertThat(registerRequest()).isEqualTo(registerRequest()).hasSameHashCodeAs(registerRequest());
    RegisterRequest request = registerRequest();
    assertThat(request).isEqualTo(request).isNotEqualTo(null).isNotEqualTo("register");
    assertThat(mutateRegister(r -> r.setEmail("other@otterworks.dev")))
        .isNotEqualTo(registerRequest());
    assertThat(mutateRegister(r -> r.setPassword("other-password")))
        .isNotEqualTo(registerRequest());
    assertThat(mutateRegister(r -> r.setDisplayName("Other"))).isNotEqualTo(registerRequest());
    assertThat(mutateRegister(r -> r.setEmail(null))).isNotEqualTo(registerRequest());
    assertThat(registerRequest()).isNotEqualTo(mutateRegister(r -> r.setEmail(null)));
    assertThat(mutateRegister(r -> r.setPassword(null))).isNotEqualTo(registerRequest());
    assertThat(mutateRegister(r -> r.setDisplayName(null))).isNotEqualTo(registerRequest());
    assertThat(new RegisterRequest())
        .isEqualTo(new RegisterRequest())
        .hasSameHashCodeAs(new RegisterRequest());
    assertThat(request.toString()).contains("user@otterworks.dev");
  }

  @Test
  void loginRequestAcceptsAValidPayload() {
    assertThat(validator.validate(loginRequest())).isEmpty();
  }

  @ParameterizedTest
  @ValueSource(strings = {"", " ", "no-at-sign", "@otterworks.dev"})
  void loginRequestRejectsInvalidEmails(String email) {
    LoginRequest request = loginRequest();
    request.setEmail(email);

    assertThat(validator.validate(request)).isNotEmpty();
  }

  @Test
  void loginRequestRejectsBlankPassword() {
    LoginRequest request = loginRequest();
    request.setPassword("  ");

    assertThat(validator.validate(request)).isNotEmpty();
  }

  @Test
  void loginRequestValueSemantics() {
    assertThat(loginRequest()).isEqualTo(loginRequest()).hasSameHashCodeAs(loginRequest());
    LoginRequest request = loginRequest();
    assertThat(request).isEqualTo(request).isNotEqualTo(null).isNotEqualTo("login");
    LoginRequest other = loginRequest();
    other.setEmail("other@otterworks.dev");
    assertThat(other).isNotEqualTo(loginRequest());
    other = loginRequest();
    other.setPassword("other");
    assertThat(other).isNotEqualTo(loginRequest());
    other = loginRequest();
    other.setEmail(null);
    assertThat(other).isNotEqualTo(loginRequest());
    assertThat(loginRequest()).isNotEqualTo(other);
    other = loginRequest();
    other.setPassword(null);
    assertThat(other).isNotEqualTo(loginRequest());
    assertThat(new LoginRequest()).isEqualTo(new LoginRequest());
    assertThat(request.toString()).contains("user@otterworks.dev");
  }

  @Test
  void changePasswordRequestEnforcesNewPasswordLength() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("old-password");
    request.setNewPassword("new-password");
    assertThat(validator.validate(request)).isEmpty();

    request.setNewPassword("short");
    assertThat(validator.validate(request)).isNotEmpty();

    request.setNewPassword("x".repeat(129));
    assertThat(validator.validate(request)).isNotEmpty();

    request.setNewPassword("new-password");
    request.setCurrentPassword("");
    assertThat(validator.validate(request)).isNotEmpty();
  }

  @Test
  void changePasswordRequestValueSemantics() {
    ChangePasswordRequest request = changePasswordRequest();
    assertThat(request)
        .isEqualTo(changePasswordRequest())
        .hasSameHashCodeAs(changePasswordRequest())
        .isEqualTo(request)
        .isNotEqualTo(null)
        .isNotEqualTo("change");
    ChangePasswordRequest other = changePasswordRequest();
    other.setCurrentPassword("different");
    assertThat(other).isNotEqualTo(changePasswordRequest());
    other = changePasswordRequest();
    other.setNewPassword("different");
    assertThat(other).isNotEqualTo(changePasswordRequest());
    other = changePasswordRequest();
    other.setCurrentPassword(null);
    assertThat(other).isNotEqualTo(changePasswordRequest());
    assertThat(changePasswordRequest()).isNotEqualTo(other);
    other = changePasswordRequest();
    other.setNewPassword(null);
    assertThat(other).isNotEqualTo(changePasswordRequest());
    assertThat(new ChangePasswordRequest()).isEqualTo(new ChangePasswordRequest());
  }

  @Test
  void updateProfileRequestAllowsAllFieldsAbsent() {
    assertThat(validator.validate(new UpdateProfileRequest())).isEmpty();
  }

  @Test
  void updateProfileRequestEnforcesFieldSizes() {
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("");
    assertThat(validator.validate(request)).isNotEmpty();

    request.setDisplayName("x".repeat(101));
    assertThat(validator.validate(request)).isNotEmpty();

    request.setDisplayName("Fine");
    request.setAvatarUrl("x".repeat(501));
    assertThat(validator.validate(request)).isNotEmpty();

    request.setAvatarUrl("https://cdn.otterworks.dev/a.png");
    assertThat(validator.validate(request)).isEmpty();
  }

  @Test
  void updateProfileRequestValueSemantics() {
    UpdateProfileRequest request = updateProfileRequest();
    assertThat(request)
        .isEqualTo(updateProfileRequest())
        .hasSameHashCodeAs(updateProfileRequest())
        .isEqualTo(request)
        .isNotEqualTo(null)
        .isNotEqualTo("profile");
    UpdateProfileRequest other = updateProfileRequest();
    other.setDisplayName("Other");
    assertThat(other).isNotEqualTo(updateProfileRequest());
    other = updateProfileRequest();
    other.setAvatarUrl("other");
    assertThat(other).isNotEqualTo(updateProfileRequest());
    other = updateProfileRequest();
    other.setDisplayName(null);
    assertThat(other).isNotEqualTo(updateProfileRequest());
    assertThat(updateProfileRequest()).isNotEqualTo(other);
    other = updateProfileRequest();
    other.setAvatarUrl(null);
    assertThat(other).isNotEqualTo(updateProfileRequest());
    assertThat(new UpdateProfileRequest()).isEqualTo(new UpdateProfileRequest());
    assertThat(request.toString()).contains("Profile User");
  }

  @Test
  void updateSettingsRequestDefaultsToAllFieldsAbsent() {
    UpdateSettingsRequest request = new UpdateSettingsRequest();

    assertThat(request.getNotificationEmail()).isNull();
    assertThat(request.getNotificationInApp()).isNull();
    assertThat(request.getNotificationDesktop()).isNull();
    assertThat(request.getTheme()).isNull();
    assertThat(request.getLanguage()).isNull();
  }

  @Test
  void updateSettingsRequestMutatorsRoundTripEveryField() {
    UpdateSettingsRequest request = new UpdateSettingsRequest();

    request.setNotificationEmail(true);
    request.setNotificationInApp(false);
    request.setNotificationDesktop(true);
    request.setTheme("dark");
    request.setLanguage("nl");

    assertThat(request.getNotificationEmail()).isTrue();
    assertThat(request.getNotificationInApp()).isFalse();
    assertThat(request.getNotificationDesktop()).isTrue();
    assertThat(request.getTheme()).isEqualTo("dark");
    assertThat(request.getLanguage()).isEqualTo("nl");
    assertThat(request.toString()).contains("dark", "nl");
  }

  @Test
  void updateSettingsRequestValueSemantics() {
    UpdateSettingsRequest request = updateSettingsRequest();
    assertThat(request)
        .isEqualTo(updateSettingsRequest())
        .hasSameHashCodeAs(updateSettingsRequest())
        .isEqualTo(request)
        .isNotEqualTo(null)
        .isNotEqualTo("settings");
    assertThat(new UpdateSettingsRequest())
        .isEqualTo(new UpdateSettingsRequest())
        .hasSameHashCodeAs(new UpdateSettingsRequest())
        .isNotEqualTo(request);
  }

  @Test
  void updateSettingsRequestAnyDifferingFieldBreaksEquality() {
    assertThat(mutateSettings(r -> r.setNotificationEmail(true)))
        .isNotEqualTo(updateSettingsRequest());
    assertThat(mutateSettings(r -> r.setNotificationInApp(true)))
        .isNotEqualTo(updateSettingsRequest());
    assertThat(mutateSettings(r -> r.setNotificationDesktop(false)))
        .isNotEqualTo(updateSettingsRequest());
    assertThat(mutateSettings(r -> r.setTheme("light"))).isNotEqualTo(updateSettingsRequest());
    assertThat(mutateSettings(r -> r.setLanguage("en"))).isNotEqualTo(updateSettingsRequest());
    assertThat(mutateSettings(r -> r.setNotificationEmail(null)))
        .isNotEqualTo(updateSettingsRequest());
    assertThat(updateSettingsRequest())
        .isNotEqualTo(mutateSettings(r -> r.setNotificationEmail(null)));
    assertThat(mutateSettings(r -> r.setNotificationInApp(null)))
        .isNotEqualTo(updateSettingsRequest());
    assertThat(mutateSettings(r -> r.setNotificationDesktop(null)))
        .isNotEqualTo(updateSettingsRequest());
    assertThat(mutateSettings(r -> r.setTheme(null))).isNotEqualTo(updateSettingsRequest());
    assertThat(mutateSettings(r -> r.setLanguage(null))).isNotEqualTo(updateSettingsRequest());
  }

  private static RegisterRequest registerRequest() {
    RegisterRequest request = new RegisterRequest();
    request.setEmail("user@otterworks.dev");
    request.setPassword("password123");
    request.setDisplayName("Register User");
    return request;
  }

  private static RegisterRequest mutateRegister(Consumer<RegisterRequest> change) {
    RegisterRequest request = registerRequest();
    change.accept(request);
    return request;
  }

  private static LoginRequest loginRequest() {
    LoginRequest request = new LoginRequest();
    request.setEmail("user@otterworks.dev");
    request.setPassword("password123");
    return request;
  }

  private static ChangePasswordRequest changePasswordRequest() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("old-password");
    request.setNewPassword("new-password");
    return request;
  }

  private static UpdateProfileRequest updateProfileRequest() {
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("Profile User");
    request.setAvatarUrl("https://cdn.otterworks.dev/p.png");
    return request;
  }

  private static UpdateSettingsRequest updateSettingsRequest() {
    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setNotificationEmail(false);
    request.setNotificationInApp(false);
    request.setNotificationDesktop(true);
    request.setTheme("dark");
    request.setLanguage("it");
    return request;
  }

  private static UpdateSettingsRequest mutateSettings(Consumer<UpdateSettingsRequest> change) {
    UpdateSettingsRequest request = updateSettingsRequest();
    change.accept(request);
    return request;
  }
}
