package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.function.Consumer;
import java.util.function.Supplier;
import org.junit.jupiter.api.Test;

/**
 * The auth DTOs are value objects on the wire: two payloads carrying the same fields must be equal
 * and hash alike, and a difference in any single field must break equality. Each field is checked
 * in isolation because equality short-circuits on the first mismatch.
 */
class DtoValueSemanticsTest {

  private static final Instant CREATED = Instant.parse("2024-01-01T00:00:00Z");
  private static final Instant UPDATED = Instant.parse("2024-02-01T00:00:00Z");
  private static final Instant LAST_LOGIN = Instant.parse("2024-03-01T00:00:00Z");
  private static final String USER_ID = UUID.nameUUIDFromBytes("dto".getBytes()).toString();

  @Test
  void authResponseIsAValueObject() {
    assertEqualityContract(
        () ->
            new AuthResponse(
                "access", "refresh", "Bearer", 3600L, new AuthResponse.UserDto("1", "e", "n", "a")),
        List.of(
            dto -> dto.setAccessToken("other"),
            dto -> dto.setRefreshToken("other"),
            dto -> dto.setTokenType("Basic"),
            dto -> dto.setExpiresIn(60L),
            dto -> dto.setUser(new AuthResponse.UserDto("2", "e", "n", "a"))));
    assertNullFieldContract(
        () -> new AuthResponse(null, null, null, 0L, null),
        List.of(
            dto -> dto.setAccessToken("access"),
            dto -> dto.setRefreshToken("refresh"),
            dto -> dto.setTokenType("Bearer"),
            dto -> dto.setUser(new AuthResponse.UserDto("1", "e", "n", "a"))));
  }

  @Test
  void authResponseUserDtoIsAValueObject() {
    assertEqualityContract(
        () -> new AuthResponse.UserDto("1", "user@otterworks.dev", "User", "avatar"),
        List.of(
            dto -> dto.setId("2"),
            dto -> dto.setEmail("other@otterworks.dev"),
            dto -> dto.setDisplayName("Other"),
            dto -> dto.setAvatarUrl("other-avatar")));
    assertNullFieldContract(
        () -> new AuthResponse.UserDto(null, null, null, null),
        List.of(
            dto -> dto.setId("1"),
            dto -> dto.setEmail("user@otterworks.dev"),
            dto -> dto.setDisplayName("User"),
            dto -> dto.setAvatarUrl("avatar")));
  }

  @Test
  void userDtoIsAValueObject() {
    assertEqualityContract(
        DtoValueSemanticsTest::userDto,
        List.of(
            dto -> dto.setId(UUID.randomUUID().toString()),
            dto -> dto.setEmail("other@otterworks.dev"),
            dto -> dto.setDisplayName("Other"),
            dto -> dto.setAvatarUrl("other-avatar"),
            dto -> dto.setRoles(Set.of("ADMIN")),
            dto -> dto.setEmailVerified(false),
            dto -> dto.setCreatedAt(UPDATED),
            dto -> dto.setUpdatedAt(CREATED),
            dto -> dto.setLastLoginAt(CREATED)));
    assertNullFieldContract(
        UserDTO::new,
        List.of(
            dto -> dto.setId(USER_ID),
            dto -> dto.setEmail("user@otterworks.dev"),
            dto -> dto.setDisplayName("User"),
            dto -> dto.setAvatarUrl("avatar"),
            dto -> dto.setRoles(Set.of("USER")),
            dto -> dto.setCreatedAt(CREATED),
            dto -> dto.setUpdatedAt(UPDATED),
            dto -> dto.setLastLoginAt(LAST_LOGIN)));
  }

  @Test
  void userDtoAllArgsConstructorMatchesTheSetterBuiltInstance() {
    UserDTO constructed =
        new UserDTO(
            USER_ID,
            "user@otterworks.dev",
            "User",
            "avatar",
            Set.of("USER"),
            true,
            CREATED,
            UPDATED,
            LAST_LOGIN);

    assertThat(constructed).isEqualTo(userDto());
  }

  @Test
  void userDtoToStringExposesTheIdentityFields() {
    assertThat(userDto().toString())
        .contains(USER_ID)
        .contains("user@otterworks.dev")
        .contains("User");
  }

  @Test
  void userLookupResponseIsAValueObject() {
    assertEqualityContract(
        () -> new UserLookupResponse(USER_ID, "user@otterworks.dev", "User"),
        List.of(
            dto -> dto.setId(UUID.randomUUID().toString()),
            dto -> dto.setEmail("other@otterworks.dev"),
            dto -> dto.setDisplayName("Other")));
    assertNullFieldContract(
        () -> new UserLookupResponse(null, null, null),
        List.of(
            dto -> dto.setId(USER_ID),
            dto -> dto.setEmail("user@otterworks.dev"),
            dto -> dto.setDisplayName("User")));
  }

  @Test
  void userSettingsDtoIsAValueObject() {
    assertEqualityContract(
        () -> new UserSettingsDTO(true, true, false, "system", "en"),
        List.of(
            dto -> dto.setNotificationEmail(false),
            dto -> dto.setNotificationInApp(false),
            dto -> dto.setNotificationDesktop(true),
            dto -> dto.setTheme("dark"),
            dto -> dto.setLanguage("fr")));
    assertNullFieldContract(
        UserSettingsDTO::new, List.of(dto -> dto.setTheme("dark"), dto -> dto.setLanguage("fr")));
  }

  @Test
  void updateSettingsRequestIsAValueObject() {
    assertEqualityContract(
        () -> {
          UpdateSettingsRequest request = new UpdateSettingsRequest();
          request.setNotificationEmail(true);
          request.setNotificationInApp(true);
          request.setNotificationDesktop(false);
          request.setTheme("system");
          request.setLanguage("en");
          return request;
        },
        List.of(
            request -> request.setNotificationEmail(false),
            request -> request.setNotificationInApp(false),
            request -> request.setNotificationDesktop(true),
            request -> request.setTheme("dark"),
            request -> request.setLanguage("fr")));
    assertNullFieldContract(
        UpdateSettingsRequest::new,
        List.of(
            request -> request.setNotificationEmail(true),
            request -> request.setNotificationInApp(true),
            request -> request.setNotificationDesktop(true),
            request -> request.setTheme("dark"),
            request -> request.setLanguage("fr")));
  }

  @Test
  void loginRequestIsAValueObject() {
    assertEqualityContract(
        () -> {
          LoginRequest request = new LoginRequest();
          request.setEmail("user@otterworks.dev");
          request.setPassword("password123");
          return request;
        },
        List.of(
            request -> request.setEmail("other@otterworks.dev"),
            request -> request.setPassword("other-password")));
    assertNullFieldContract(
        LoginRequest::new,
        List.of(
            request -> request.setEmail("user@otterworks.dev"),
            request -> request.setPassword("password123")));
  }

  @Test
  void registerRequestIsAValueObject() {
    assertEqualityContract(
        () -> {
          RegisterRequest request = new RegisterRequest();
          request.setEmail("user@otterworks.dev");
          request.setPassword("password123");
          request.setDisplayName("User");
          return request;
        },
        List.of(
            request -> request.setEmail("other@otterworks.dev"),
            request -> request.setPassword("other-password"),
            request -> request.setDisplayName("Other")));
    assertNullFieldContract(
        RegisterRequest::new,
        List.of(
            request -> request.setEmail("user@otterworks.dev"),
            request -> request.setPassword("password123"),
            request -> request.setDisplayName("User")));
  }

  @Test
  void changePasswordRequestIsAValueObject() {
    assertEqualityContract(
        () -> {
          ChangePasswordRequest request = new ChangePasswordRequest();
          request.setCurrentPassword("password123");
          request.setNewPassword("password456");
          return request;
        },
        List.of(
            request -> request.setCurrentPassword("other"),
            request -> request.setNewPassword("other")));
    assertNullFieldContract(
        ChangePasswordRequest::new,
        List.of(
            request -> request.setCurrentPassword("password123"),
            request -> request.setNewPassword("password456")));
  }

  @Test
  void changePasswordRequestToStringDoesNotHideItsFieldNames() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("password123");
    request.setNewPassword("password456");

    assertThat(request.toString()).contains("currentPassword").contains("newPassword");
  }

  @Test
  void updateProfileRequestIsAValueObject() {
    assertEqualityContract(
        () -> {
          UpdateProfileRequest request = new UpdateProfileRequest();
          request.setDisplayName("User");
          request.setAvatarUrl("avatar");
          return request;
        },
        List.of(
            request -> request.setDisplayName("Other"),
            request -> request.setAvatarUrl("other-avatar")));
    assertNullFieldContract(
        UpdateProfileRequest::new,
        List.of(
            request -> request.setDisplayName("User"), request -> request.setAvatarUrl("avatar")));
  }

  private static UserDTO userDto() {
    UserDTO dto = new UserDTO();
    dto.setId(USER_ID);
    dto.setEmail("user@otterworks.dev");
    dto.setDisplayName("User");
    dto.setAvatarUrl("avatar");
    dto.setRoles(Set.of("USER"));
    dto.setEmailVerified(true);
    dto.setCreatedAt(CREATED);
    dto.setUpdatedAt(UPDATED);
    dto.setLastLoginAt(LAST_LOGIN);
    return dto;
  }

  /** Two independently built instances are equal, and changing any single field breaks that. */
  private static <T> void assertEqualityContract(
      Supplier<T> factory, List<Consumer<T>> perFieldChanges) {
    T instance = factory.get();
    T twin = factory.get();

    assertThat(instance).isEqualTo(instance).isEqualTo(twin).hasSameHashCodeAs(twin);
    assertThat(instance).isNotEqualTo(null).isNotEqualTo("a string of another type");
    assertThat(instance.toString()).isEqualTo(twin.toString());

    for (Consumer<T> change : perFieldChanges) {
      T changed = factory.get();
      change.accept(changed);

      assertThat(changed).isNotEqualTo(instance);
      assertThat(instance).isNotEqualTo(changed);
    }
  }

  /** An unset field is only equal to another unset field, in either comparison direction. */
  private static <T> void assertNullFieldContract(
      Supplier<T> emptyFactory, List<Consumer<T>> perFieldPopulations) {
    T empty = emptyFactory.get();

    assertThat(empty).isEqualTo(emptyFactory.get()).hasSameHashCodeAs(emptyFactory.get());

    for (Consumer<T> populate : perFieldPopulations) {
      T populated = emptyFactory.get();
      populate.accept(populated);

      assertThat(populated).isNotEqualTo(empty);
      assertThat(empty).isNotEqualTo(populated);
      assertThat(populated.hashCode()).isNotEqualTo(empty.hashCode());
    }
  }
}
