package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import com.otterworks.auth.entity.User;
import com.otterworks.auth.entity.UserSettings;
import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import java.util.function.Consumer;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

/**
 * The DTOs are Lombok value types exchanged over the wire; these tests pin their mapping and their
 * equals/hashCode/toString contracts, which the gateway and the web app rely on.
 */
class DtoValueSemanticsTest {

  private User user(UUID id) {
    User user = new User();
    user.setId(id);
    user.setEmail("dto@otterworks.dev");
    user.setDisplayName("Dto User");
    user.setAvatarUrl("https://cdn.otterworks.dev/dto.png");
    user.setEmailVerified(true);
    user.setRoles(Set.of(User.Role.USER, User.Role.OWNER));
    return user;
  }

  @Test
  void userDtoFromEntityCopiesEveryExposedField() {
    UUID id = UUID.randomUUID();
    Instant now = Instant.parse("2024-01-01T00:00:00Z");
    User user = user(id);
    user.setLastLoginAt(now);

    UserDTO dto = UserDTO.fromEntity(user);

    assertThat(dto.getId()).isEqualTo(id.toString());
    assertThat(dto.getEmail()).isEqualTo("dto@otterworks.dev");
    assertThat(dto.getDisplayName()).isEqualTo("Dto User");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/dto.png");
    assertThat(dto.getRoles()).containsExactlyInAnyOrder("USER", "OWNER");
    assertThat(dto.isEmailVerified()).isTrue();
    assertThat(dto.getLastLoginAt()).isEqualTo(now);
    assertThat(dto.getCreatedAt()).isNull();
    assertThat(dto.getUpdatedAt()).isNull();
  }

  @Test
  void userDtoNeverExposesThePasswordHash() {
    User user = user(UUID.randomUUID());
    user.setPasswordHash(
        "$2a$12$hashedpassword"); // nosemgrep: generic.secrets.security.detected-bcrypt-hash

    assertThat(UserDTO.fromEntity(user).toString()).doesNotContain("hashedpassword");
  }

  @Test
  void userDtoEqualityIsByValue() {
    UUID id = UUID.randomUUID();
    UserDTO first = UserDTO.fromEntity(user(id));
    UserDTO second = UserDTO.fromEntity(user(id));

    assertThat(first).isEqualTo(second).hasSameHashCodeAs(second);

    second.setDisplayName("Other");
    assertThat(first).isNotEqualTo(second);
    assertThat(first).isNotEqualTo(null);
    assertThat(first).isNotEqualTo("not a dto");
  }

  @Test
  void userLookupResponseKeepsOnlyTheDirectoryFields() {
    UUID id = UUID.randomUUID();
    UserDTO source = UserDTO.fromEntity(user(id));

    UserLookupResponse lookup = UserLookupResponse.fromUserDTO(source);

    assertThat(lookup.getId()).isEqualTo(id.toString());
    assertThat(lookup.getEmail()).isEqualTo("dto@otterworks.dev");
    assertThat(lookup.getDisplayName()).isEqualTo("Dto User");
    assertThat(lookup.toString()).doesNotContain("cdn.otterworks.dev");
    assertThat(lookup)
        .isEqualTo(new UserLookupResponse(id.toString(), "dto@otterworks.dev", "Dto User"))
        .hasSameHashCodeAs(new UserLookupResponse(id.toString(), "dto@otterworks.dev", "Dto User"));
    assertThat(lookup)
        .isNotEqualTo(new UserLookupResponse(id.toString(), "other@otterworks.dev", "Dto User"));
  }

  @Test
  void userSettingsDtoFromEntityCopiesEveryField() {
    UserSettings entity = new UserSettings();
    entity.setNotificationEmail(false);
    entity.setNotificationInApp(false);
    entity.setNotificationDesktop(true);
    entity.setTheme("dark");
    entity.setLanguage("ja");

    UserSettingsDTO dto = UserSettingsDTO.fromEntity(entity);

    assertThat(dto).isEqualTo(new UserSettingsDTO(false, false, true, "dark", "ja"));
    assertThat(dto).hasSameHashCodeAs(new UserSettingsDTO(false, false, true, "dark", "ja"));
    assertThat(dto).isNotEqualTo(new UserSettingsDTO(true, false, true, "dark", "ja"));
    assertThat(dto).isNotEqualTo(new UserSettingsDTO(false, true, true, "dark", "ja"));
    assertThat(dto).isNotEqualTo(new UserSettingsDTO(false, false, false, "dark", "ja"));
    assertThat(dto).isNotEqualTo(new UserSettingsDTO(false, false, true, "light", "ja"));
    assertThat(dto).isNotEqualTo(new UserSettingsDTO(false, false, true, "dark", "en"));
    assertThat(dto).isNotEqualTo(new UserSettingsDTO());
    assertThat(dto.toString()).contains("dark", "ja");
  }

  @Test
  void updateSettingsRequestTreatsUnsetFieldsAsNull() {
    UpdateSettingsRequest request = new UpdateSettingsRequest();

    assertThat(request.getNotificationEmail()).isNull();
    assertThat(request.getNotificationInApp()).isNull();
    assertThat(request.getNotificationDesktop()).isNull();
    assertThat(request.getTheme()).isNull();
    assertThat(request.getLanguage()).isNull();
    assertThat(request).isEqualTo(new UpdateSettingsRequest());
    assertThat(request).hasSameHashCodeAs(new UpdateSettingsRequest());

    request.setNotificationEmail(true);
    request.setNotificationInApp(false);
    request.setNotificationDesktop(true);
    request.setTheme("light");
    request.setLanguage("es");

    assertThat(request.getNotificationEmail()).isTrue();
    assertThat(request.getNotificationInApp()).isFalse();
    assertThat(request.getNotificationDesktop()).isTrue();
    assertThat(request).isNotEqualTo(new UpdateSettingsRequest());
    assertThat(request.toString()).contains("light", "es");
  }

  @Test
  void authResponseCarriesTheTokenPairAndTheUserSummary() {
    AuthResponse.UserDto summary =
        new AuthResponse.UserDto("id-1", "dto@otterworks.dev", "Dto User", null);
    AuthResponse response = authResponse();

    assertThat(response.getAccessToken()).isEqualTo("access");
    assertThat(response.getRefreshToken()).isEqualTo("refresh");
    assertThat(response.getTokenType()).isEqualTo("Bearer");
    assertThat(response.getExpiresIn()).isEqualTo(3600L);
    assertThat(response.getUser()).isEqualTo(summary).hasSameHashCodeAs(summary);
    assertThat(response)
        .isEqualTo(new AuthResponse("access", "refresh", "Bearer", 3600L, summary))
        .isNotEqualTo(new AuthResponse("access", "refresh", "Bearer", 60L, summary));
    assertThat(response.getUser())
        .isNotEqualTo(new AuthResponse.UserDto("id-2", "dto@otterworks.dev", "Dto User", null));
    assertThat(response.toString()).contains("Bearer");
  }

  @Test
  void credentialRequestsExposeTheirFieldsAsValues() {
    RegisterRequest register = new RegisterRequest();
    register.setEmail("new@otterworks.dev");
    register.setPassword("password123");
    register.setDisplayName("New User");

    LoginRequest login = new LoginRequest();
    login.setEmail("new@otterworks.dev");
    login.setPassword("password123");

    ChangePasswordRequest change = new ChangePasswordRequest();
    change.setCurrentPassword("password123");
    change.setNewPassword("password456");

    UpdateProfileRequest profile = new UpdateProfileRequest();
    profile.setDisplayName("New Name");
    profile.setAvatarUrl("https://cdn.otterworks.dev/n.png");

    assertThat(register.getEmail()).isEqualTo("new@otterworks.dev");
    assertThat(register.getDisplayName()).isEqualTo("New User");
    assertThat(register).isEqualTo(register).isNotEqualTo(new RegisterRequest());
    assertThat(login.getPassword()).isEqualTo("password123");
    assertThat(login).isNotEqualTo(new LoginRequest());
    assertThat(login).hasSameHashCodeAs(loginCopy());
    assertThat(change.getCurrentPassword()).isEqualTo("password123");
    assertThat(change.getNewPassword()).isEqualTo("password456");
    assertThat(change).isNotEqualTo(new ChangePasswordRequest());
    assertThat(profile.getDisplayName()).isEqualTo("New Name");
    assertThat(profile.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/n.png");
    assertThat(profile).isNotEqualTo(new UpdateProfileRequest());
    assertThat(profile.toString()).contains("New Name");
  }

  @ParameterizedTest(name = "UserDTO differing in {0} is not equal")
  @MethodSource("userDtoMutators")
  void userDtoEqualityDistinguishesEveryField(String field, Consumer<UserDTO> mutate) {
    UUID id = UUID.randomUUID();
    UserDTO reference = UserDTO.fromEntity(user(id));
    UserDTO mutated = UserDTO.fromEntity(user(id));
    mutate.accept(mutated);

    assertThat(mutated).as("field %s", field).isNotEqualTo(reference);
    assertThat(reference).isNotEqualTo(mutated);
  }

  private static Stream<Arguments> userDtoMutators() {
    return Stream.of(
        Arguments.of("id", (Consumer<UserDTO>) dto -> dto.setId(UUID.randomUUID().toString())),
        Arguments.of("email", (Consumer<UserDTO>) dto -> dto.setEmail("other@otterworks.dev")),
        Arguments.of("displayName", (Consumer<UserDTO>) dto -> dto.setDisplayName("Other")),
        Arguments.of("avatarUrl", (Consumer<UserDTO>) dto -> dto.setAvatarUrl(null)),
        Arguments.of("roles", (Consumer<UserDTO>) dto -> dto.setRoles(Set.of("ADMIN"))),
        Arguments.of("emailVerified", (Consumer<UserDTO>) dto -> dto.setEmailVerified(false)),
        Arguments.of("createdAt", (Consumer<UserDTO>) dto -> dto.setCreatedAt(Instant.EPOCH)),
        Arguments.of("updatedAt", (Consumer<UserDTO>) dto -> dto.setUpdatedAt(Instant.EPOCH)),
        Arguments.of("lastLoginAt", (Consumer<UserDTO>) dto -> dto.setLastLoginAt(Instant.EPOCH)),
        Arguments.of("id=null", (Consumer<UserDTO>) dto -> dto.setId(null)),
        Arguments.of("email=null", (Consumer<UserDTO>) dto -> dto.setEmail(null)),
        Arguments.of("displayName=null", (Consumer<UserDTO>) dto -> dto.setDisplayName(null)),
        Arguments.of("roles=null", (Consumer<UserDTO>) dto -> dto.setRoles(null)));
  }

  @ParameterizedTest(name = "AuthResponse differing in {0} is not equal")
  @MethodSource("authResponseVariants")
  void authResponseEqualityDistinguishesEveryField(String field, AuthResponse variant) {
    AuthResponse reference = authResponse();

    assertThat(variant).as("field %s", field).isNotEqualTo(reference);
    assertThat(reference).isNotEqualTo(variant);
  }

  private static AuthResponse authResponse() {
    return new AuthResponse(
        "access",
        "refresh",
        "Bearer",
        3600L,
        new AuthResponse.UserDto("id-1", "dto@otterworks.dev", "Dto User", null));
  }

  private static Stream<Arguments> authResponseVariants() {
    AuthResponse.UserDto summary =
        new AuthResponse.UserDto("id-1", "dto@otterworks.dev", "Dto User", null);
    return Stream.of(
        Arguments.of("accessToken", new AuthResponse("other", "refresh", "Bearer", 3600L, summary)),
        Arguments.of("refreshToken", new AuthResponse("access", "other", "Bearer", 3600L, summary)),
        Arguments.of("tokenType", new AuthResponse("access", "refresh", "Basic", 3600L, summary)),
        Arguments.of("expiresIn", new AuthResponse("access", "refresh", "Bearer", 60L, summary)),
        Arguments.of(
            "user",
            new AuthResponse(
                "access",
                "refresh",
                "Bearer",
                3600L,
                new AuthResponse.UserDto("id-2", "dto@otterworks.dev", "Dto User", null))),
        Arguments.of(
            "accessToken=null", new AuthResponse(null, "refresh", "Bearer", 3600L, summary)),
        Arguments.of(
            "refreshToken=null", new AuthResponse("access", null, "Bearer", 3600L, summary)),
        Arguments.of("tokenType=null", new AuthResponse("access", "refresh", null, 3600L, summary)),
        Arguments.of("user=null", new AuthResponse("access", "refresh", "Bearer", 3600L, null)));
  }

  @ParameterizedTest(name = "AuthResponse.UserDto differing in {0} is not equal")
  @MethodSource("userSummaryVariants")
  void authResponseUserSummaryEqualityDistinguishesEveryField(
      String field, AuthResponse.UserDto variant) {
    AuthResponse.UserDto reference =
        new AuthResponse.UserDto("id-1", "dto@otterworks.dev", "Dto User", null);

    assertThat(variant).as("field %s", field).isNotEqualTo(reference);
    assertThat(reference).isNotEqualTo(variant);
  }

  private static Stream<Arguments> userSummaryVariants() {
    return Stream.of(
        Arguments.of(
            "id", new AuthResponse.UserDto("id-2", "dto@otterworks.dev", "Dto User", null)),
        Arguments.of(
            "email", new AuthResponse.UserDto("id-1", "other@otterworks.dev", "Dto User", null)),
        Arguments.of(
            "displayName", new AuthResponse.UserDto("id-1", "dto@otterworks.dev", "Other", null)),
        Arguments.of(
            "avatarUrl",
            new AuthResponse.UserDto("id-1", "dto@otterworks.dev", "Dto User", "https://a")),
        Arguments.of(
            "id=null", new AuthResponse.UserDto(null, "dto@otterworks.dev", "Dto User", null)),
        Arguments.of("email=null", new AuthResponse.UserDto("id-1", null, "Dto User", null)),
        Arguments.of(
            "displayName=null",
            new AuthResponse.UserDto("id-1", "dto@otterworks.dev", null, null)));
  }

  @ParameterizedTest(name = "UpdateSettingsRequest differing in {0} is not equal")
  @MethodSource("updateSettingsMutators")
  void updateSettingsRequestEqualityDistinguishesEveryField(
      String field, Consumer<UpdateSettingsRequest> mutate) {
    UpdateSettingsRequest reference = new UpdateSettingsRequest();
    UpdateSettingsRequest mutated = new UpdateSettingsRequest();
    mutate.accept(mutated);

    assertThat(mutated).as("field %s", field).isNotEqualTo(reference);
    assertThat(reference).isNotEqualTo(mutated);
  }

  private static Stream<Arguments> updateSettingsMutators() {
    return Stream.of(
        Arguments.of(
            "notificationEmail",
            (Consumer<UpdateSettingsRequest>) r -> r.setNotificationEmail(false)),
        Arguments.of(
            "notificationInApp",
            (Consumer<UpdateSettingsRequest>) r -> r.setNotificationInApp(false)),
        Arguments.of(
            "notificationDesktop",
            (Consumer<UpdateSettingsRequest>) r -> r.setNotificationDesktop(true)),
        Arguments.of("theme", (Consumer<UpdateSettingsRequest>) r -> r.setTheme("dark")),
        Arguments.of("language", (Consumer<UpdateSettingsRequest>) r -> r.setLanguage("fr")),
        Arguments.of(
            "all fields",
            (Consumer<UpdateSettingsRequest>)
                r -> {
                  r.setNotificationEmail(true);
                  r.setNotificationInApp(true);
                  r.setNotificationDesktop(true);
                  r.setTheme("light");
                  r.setLanguage("de");
                }));
  }

  @ParameterizedTest(name = "credential request differing in {0} is not equal")
  @MethodSource("credentialVariants")
  void credentialRequestEqualityDistinguishesEveryField(String field, Object variant) {
    Object reference =
        switch (field.split("\\.")[0]) {
          case "register" -> registerRequest("new@otterworks.dev", "password123", "New User");
          case "login" -> loginCopy();
          case "change" -> changePasswordRequest("password123", "password456");
          default -> updateProfileRequest("New Name", "https://cdn.otterworks.dev/n.png");
        };

    assertThat(variant).as("field %s", field).isNotEqualTo(reference);
    assertThat(reference).isNotEqualTo(variant);
  }

  private static Stream<Arguments> credentialVariants() {
    return Stream.of(
        Arguments.of(
            "register.email", registerRequest("x@otterworks.dev", "password123", "New User")),
        Arguments.of(
            "register.password", registerRequest("new@otterworks.dev", "other", "New User")),
        Arguments.of(
            "register.displayName", registerRequest("new@otterworks.dev", "password123", "Other")),
        Arguments.of("login.email", loginRequest("x@otterworks.dev", "password123")),
        Arguments.of("login.password", loginRequest("new@otterworks.dev", "other")),
        Arguments.of("change.currentPassword", changePasswordRequest("other", "password456")),
        Arguments.of("change.newPassword", changePasswordRequest("password123", "other")),
        Arguments.of(
            "profile.displayName",
            updateProfileRequest("Other", "https://cdn.otterworks.dev/n.png")),
        Arguments.of("profile.avatarUrl", updateProfileRequest("New Name", null)),
        Arguments.of("register.email=null", registerRequest(null, "password123", "New User")),
        Arguments.of(
            "register.password=null", registerRequest("new@otterworks.dev", null, "New User")),
        Arguments.of(
            "register.displayName=null",
            registerRequest("new@otterworks.dev", "password123", null)),
        Arguments.of("login.email=null", loginRequest(null, "password123")),
        Arguments.of("login.password=null", loginRequest("new@otterworks.dev", null)),
        Arguments.of("change.currentPassword=null", changePasswordRequest(null, "password456")),
        Arguments.of("change.newPassword=null", changePasswordRequest("password123", null)),
        Arguments.of(
            "profile.displayName=null",
            updateProfileRequest(null, "https://cdn.otterworks.dev/n.png")));
  }

  private static RegisterRequest registerRequest(String email, String password, String name) {
    RegisterRequest request = new RegisterRequest();
    request.setEmail(email);
    request.setPassword(password);
    request.setDisplayName(name);
    return request;
  }

  private static LoginRequest loginRequest(String email, String password) {
    LoginRequest request = new LoginRequest();
    request.setEmail(email);
    request.setPassword(password);
    return request;
  }

  private static ChangePasswordRequest changePasswordRequest(String current, String updated) {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword(current);
    request.setNewPassword(updated);
    return request;
  }

  private static UpdateProfileRequest updateProfileRequest(String name, String avatarUrl) {
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName(name);
    request.setAvatarUrl(avatarUrl);
    return request;
  }

  @ParameterizedTest(name = "UserLookupResponse differing in {0} is not equal")
  @MethodSource("lookupVariants")
  void userLookupResponseEqualityDistinguishesEveryField(String field, UserLookupResponse variant) {
    UserLookupResponse reference = new UserLookupResponse("id-1", "dto@otterworks.dev", "Dto User");

    assertThat(variant).as("field %s", field).isNotEqualTo(reference);
    assertThat(reference).isNotEqualTo(variant);
  }

  private static Stream<Arguments> lookupVariants() {
    return Stream.of(
        Arguments.of("id", new UserLookupResponse("id-2", "dto@otterworks.dev", "Dto User")),
        Arguments.of("email", new UserLookupResponse("id-1", "other@otterworks.dev", "Dto User")),
        Arguments.of("displayName", new UserLookupResponse("id-1", "dto@otterworks.dev", "Other")),
        Arguments.of("id=null", new UserLookupResponse(null, "dto@otterworks.dev", "Dto User")),
        Arguments.of("email=null", new UserLookupResponse("id-1", null, "Dto User")),
        Arguments.of(
            "displayName=null", new UserLookupResponse("id-1", "dto@otterworks.dev", null)),
        Arguments.of("nulls", new UserLookupResponse(null, null, null)));
  }

  private LoginRequest loginCopy() {
    LoginRequest login = new LoginRequest();
    login.setEmail("new@otterworks.dev");
    login.setPassword("password123");
    return login;
  }
}
