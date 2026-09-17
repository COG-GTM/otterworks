package com.otterworks.auth.entity;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class EntityLifecycleTest {

  @Test
  void userOnCreateStampsBothTimestamps() {
    User user = new User();
    Instant before = Instant.now().minus(1, ChronoUnit.SECONDS);

    user.onCreate();

    assertThat(user.getCreatedAt()).isAfterOrEqualTo(before);
    assertThat(user.getUpdatedAt()).isAfterOrEqualTo(before);
  }

  @Test
  void userOnUpdateStampsUpdatedAtOnly() {
    User user = new User();
    user.onCreate();
    Instant created = user.getCreatedAt();

    user.onUpdate();

    assertThat(user.getCreatedAt()).isEqualTo(created);
    assertThat(user.getUpdatedAt()).isAfterOrEqualTo(created);
  }

  @Test
  void userDefaultsAreTheLeastPrivilegedOnes() {
    User user = new User();

    assertThat(user.isEmailVerified()).isFalse();
    assertThat(user.isMfaEnabled()).isFalse();
    assertThat(user.getMfaSecret()).isNull();
    assertThat(user.getRoles()).isEmpty();
    assertThat(user.getLastLoginAt()).isNull();
  }

  @Test
  void userAccessorsRoundTripEveryField() {
    UUID id = UUID.randomUUID();
    Instant lastLogin = Instant.parse("2024-06-01T12:00:00Z");
    User user = new User();

    user.setId(id);
    user.setEmail("entity@otterworks.dev");
    user.setPasswordHash("hash");
    user.setDisplayName("Entity User");
    user.setAvatarUrl("https://cdn.otterworks.dev/e.png");
    user.setEmailVerified(true);
    user.setMfaEnabled(true);
    user.setMfaSecret("secret");
    user.setRoles(Set.of(User.Role.OWNER));
    user.setLastLoginAt(lastLogin);

    assertThat(user.getId()).isEqualTo(id);
    assertThat(user.getEmail()).isEqualTo("entity@otterworks.dev");
    assertThat(user.getPasswordHash()).isEqualTo("hash");
    assertThat(user.getDisplayName()).isEqualTo("Entity User");
    assertThat(user.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/e.png");
    assertThat(user.isEmailVerified()).isTrue();
    assertThat(user.isMfaEnabled()).isTrue();
    assertThat(user.getMfaSecret()).isEqualTo("secret");
    assertThat(user.getRoles()).containsExactly(User.Role.OWNER);
    assertThat(user.getLastLoginAt()).isEqualTo(lastLogin);
  }

  @Test
  void userRoleEnumCoversTheFourKnownRoles() {
    assertThat(User.Role.values())
        .containsExactly(User.Role.USER, User.Role.EDITOR, User.Role.ADMIN, User.Role.OWNER);
    assertThat(User.Role.valueOf("ADMIN")).isEqualTo(User.Role.ADMIN);
  }

  @Test
  void refreshTokenStartsUnrevokedAndStampsCreatedAt() {
    RefreshToken token = new RefreshToken();
    Instant expiresAt = Instant.parse("2024-06-01T12:00:00Z");
    User user = new User();
    UUID id = UUID.randomUUID();

    token.setId(id);
    token.setUser(user);
    token.setTokenId("jti");
    token.setExpiresAt(expiresAt);

    assertThat(token.isRevoked()).isFalse();
    assertThat(token.getCreatedAt()).isNull();

    token.onCreate();

    assertThat(token.getId()).isEqualTo(id);
    assertThat(token.getUser()).isSameAs(user);
    assertThat(token.getTokenId()).isEqualTo("jti");
    assertThat(token.getExpiresAt()).isEqualTo(expiresAt);
    assertThat(token.getCreatedAt()).isNotNull();

    token.setRevoked(true);
    assertThat(token.isRevoked()).isTrue();
  }

  @Test
  void userSettingsDefaultToInAppAndEmailNotificationsOnSystemTheme() {
    UserSettings settings = new UserSettings();

    assertThat(settings.isNotificationEmail()).isTrue();
    assertThat(settings.isNotificationInApp()).isTrue();
    assertThat(settings.isNotificationDesktop()).isFalse();
    assertThat(settings.getTheme()).isEqualTo("system");
    assertThat(settings.getLanguage()).isEqualTo("en");
    assertThat(settings.getUserId()).isNull();
    assertThat(settings.getUser()).isNull();
  }

  @Test
  void userSettingsAccessorsRoundTripEveryField() {
    UUID userId = UUID.randomUUID();
    User user = new User();
    UserSettings settings = new UserSettings();

    settings.setUserId(userId);
    settings.setUser(user);
    settings.setNotificationEmail(false);
    settings.setNotificationInApp(false);
    settings.setNotificationDesktop(true);
    settings.setTheme("dark");
    settings.setLanguage("ja");

    assertThat(settings.getUserId()).isEqualTo(userId);
    assertThat(settings.getUser()).isSameAs(user);
    assertThat(settings.isNotificationEmail()).isFalse();
    assertThat(settings.isNotificationInApp()).isFalse();
    assertThat(settings.isNotificationDesktop()).isTrue();
    assertThat(settings.getTheme()).isEqualTo("dark");
    assertThat(settings.getLanguage()).isEqualTo("ja");
  }

  @Test
  void roleIsConstructedFromNameAndDescription() {
    Role role = new Role("ADMIN", "Full administrative access");

    assertThat(role.getId()).isNull();
    assertThat(role.getName()).isEqualTo("ADMIN");
    assertThat(role.getDescription()).isEqualTo("Full administrative access");
  }

  @Test
  void roleAccessorsRoundTripEveryField() {
    Role role = new Role();

    role.setId(7L);
    role.setName("EDITOR");
    role.setDescription("Can edit documents");

    assertThat(role.getId()).isEqualTo(7L);
    assertThat(role.getName()).isEqualTo("EDITOR");
    assertThat(role.getDescription()).isEqualTo("Can edit documents");
  }
}
