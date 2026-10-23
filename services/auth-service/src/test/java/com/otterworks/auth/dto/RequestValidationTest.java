package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.*;

import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class RequestValidationTest {

  private static Validator validator;

  @BeforeAll
  static void init() {
    validator = Validation.buildDefaultValidatorFactory().getValidator();
  }

  private static <T> Set<String> violatedFields(T bean) {
    return validator.validate(bean).stream()
        .map(ConstraintViolation::getPropertyPath)
        .map(Object::toString)
        .collect(Collectors.toSet());
  }

  private static RegisterRequest register(String email, String password, String name) {
    RegisterRequest r = new RegisterRequest();
    r.setEmail(email);
    r.setPassword(password);
    r.setDisplayName(name);
    return r;
  }

  @Test
  void register_validRequestHasNoViolations() {
    assertThat(violatedFields(register("ok@otterworks.dev", "password123", "Ok"))).isEmpty();
  }

  @ParameterizedTest
  @ValueSource(strings = {"", "not-an-email", "missing-at.example.com", "two@@example.com"})
  void register_rejectsInvalidEmail(String email) {
    assertThat(violatedFields(register(email, "password123", "Ok"))).contains("email");
  }

  @Test
  void register_rejectsNullFields() {
    assertThat(violatedFields(register(null, null, null)))
        .containsExactlyInAnyOrder("email", "password", "displayName");
  }

  @Test
  void register_passwordLengthBoundaries() {
    assertThat(violatedFields(register("a@b.dev", "1234567", "Ok"))).contains("password");
    assertThat(violatedFields(register("a@b.dev", "12345678", "Ok"))).isEmpty();
    assertThat(violatedFields(register("a@b.dev", "x".repeat(128), "Ok"))).isEmpty();
    assertThat(violatedFields(register("a@b.dev", "x".repeat(129), "Ok"))).contains("password");
  }

  @Test
  void register_displayNameBoundaries() {
    assertThat(violatedFields(register("a@b.dev", "password123", "   "))).contains("displayName");
    assertThat(violatedFields(register("a@b.dev", "password123", "x".repeat(100)))).isEmpty();
    assertThat(violatedFields(register("a@b.dev", "password123", "x".repeat(101))))
        .contains("displayName");
  }

  @Test
  void login_requiresEmailAndPassword() {
    LoginRequest r = new LoginRequest();
    assertThat(violatedFields(r)).containsExactlyInAnyOrder("email", "password");
    r.setEmail("a@b.dev");
    r.setPassword("x");
    assertThat(violatedFields(r)).isEmpty();
  }

  @Test
  void changePassword_enforcesNewPasswordLength() {
    ChangePasswordRequest r = new ChangePasswordRequest();
    r.setCurrentPassword("current");
    r.setNewPassword("short");
    assertThat(violatedFields(r)).containsExactly("newPassword");
    r.setNewPassword("long-enough");
    assertThat(violatedFields(r)).isEmpty();
    r.setCurrentPassword("");
    assertThat(violatedFields(r)).containsExactly("currentPassword");
  }

  @Test
  void updateProfile_allowsOmittedFieldsButBoundsLengths() {
    UpdateProfileRequest r = new UpdateProfileRequest();
    assertThat(violatedFields(r)).isEmpty();
    r.setDisplayName("");
    assertThat(violatedFields(r)).containsExactly("displayName");
    r.setDisplayName("x".repeat(101));
    assertThat(violatedFields(r)).containsExactly("displayName");
    r.setDisplayName("Fine");
    r.setAvatarUrl("x".repeat(501));
    assertThat(violatedFields(r)).containsExactly("avatarUrl");
  }
}
