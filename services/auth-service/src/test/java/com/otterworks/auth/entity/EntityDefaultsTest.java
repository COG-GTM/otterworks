package com.otterworks.auth.entity;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class EntityDefaultsTest {

  @Test
  void newUserStartsUnverifiedWithoutMfaAndWithoutRoles() {
    User user = new User();

    assertThat(user.isEmailVerified()).isFalse();
    assertThat(user.isMfaEnabled()).isFalse();
    assertThat(user.getMfaSecret()).isNull();
    assertThat(user.getRoles()).isEmpty();
    assertThat(user.getLastLoginAt()).isNull();
  }

  @Test
  void userMfaFieldsAreSettable() {
    User user = new User();
    user.setMfaEnabled(true);
    user.setMfaSecret("JBSWY3DPEHPK3PXP");
    user.setRoles(Set.of(User.Role.ADMIN));

    assertThat(user.isMfaEnabled()).isTrue();
    assertThat(user.getMfaSecret()).isEqualTo("JBSWY3DPEHPK3PXP");
    assertThat(user.getRoles()).containsExactly(User.Role.ADMIN);
  }

  @Test
  void userTimestampsAreStampedOnPersistAndRefreshedOnUpdate() throws InterruptedException {
    User user = new User();
    user.onCreate();

    Instant created = user.getCreatedAt();
    Instant firstUpdate = user.getUpdatedAt();
    assertThat(created).isNotNull();
    assertThat(firstUpdate).isNotNull();

    Thread.sleep(20);
    user.onUpdate();

    assertThat(user.getCreatedAt()).isEqualTo(created);
    assertThat(user.getUpdatedAt()).isAfter(firstUpdate);
  }

  @Test
  void refreshTokenStartsActiveAndIsStampedOnPersist() {
    User owner = new User();
    owner.setId(UUID.randomUUID());
    Instant expiry = Instant.parse("2024-06-01T00:00:00Z");

    RefreshToken token = new RefreshToken();
    token.setUser(owner);
    token.setTokenId("jti-1");
    token.setExpiresAt(expiry);

    assertThat(token.getId()).isNull();
    assertThat(token.isRevoked()).isFalse();
    assertThat(token.getCreatedAt()).isNull();

    token.onCreate();

    assertThat(token.getCreatedAt()).isNotNull();
    assertThat(token.getUser()).isSameAs(owner);
    assertThat(token.getTokenId()).isEqualTo("jti-1");
    assertThat(token.getExpiresAt()).isEqualTo(expiry);

    token.setRevoked(true);
    assertThat(token.isRevoked()).isTrue();
  }

  @Test
  void userSettingsDefaultToInAppAndEmailNotificationsOnly() {
    UserSettings settings = new UserSettings();

    assertThat(settings.getUserId()).isNull();
    assertThat(settings.getUser()).isNull();
    assertThat(settings.isNotificationEmail()).isTrue();
    assertThat(settings.isNotificationInApp()).isTrue();
    assertThat(settings.isNotificationDesktop()).isFalse();
    assertThat(settings.getTheme()).isEqualTo("system");
    assertThat(settings.getLanguage()).isEqualTo("en");
  }

  @Test
  void userSettingsFieldsAreSettable() {
    UUID userId = UUID.randomUUID();
    User owner = new User();
    owner.setId(userId);

    UserSettings settings = new UserSettings();
    settings.setUserId(userId);
    settings.setUser(owner);
    settings.setNotificationEmail(false);
    settings.setNotificationDesktop(true);
    settings.setTheme("dark");
    settings.setLanguage("de");

    assertThat(settings.getUserId()).isEqualTo(userId);
    assertThat(settings.getUser()).isSameAs(owner);
    assertThat(settings.isNotificationEmail()).isFalse();
    assertThat(settings.isNotificationDesktop()).isTrue();
    assertThat(settings.getTheme()).isEqualTo("dark");
    assertThat(settings.getLanguage()).isEqualTo("de");
  }

  @Test
  void roleCanBeBuiltWithOrWithoutTheConvenienceConstructor() {
    Role role = new Role("ADMIN", "Full access");

    assertThat(role.getId()).isNull();
    assertThat(role.getName()).isEqualTo("ADMIN");
    assertThat(role.getDescription()).isEqualTo("Full access");

    Role blank = new Role();
    blank.setId(7L);
    blank.setName("EDITOR");
    blank.setDescription("Can edit documents");

    assertThat(blank.getId()).isEqualTo(7L);
    assertThat(blank.getName()).isEqualTo("EDITOR");
    assertThat(blank.getDescription()).isEqualTo("Can edit documents");
  }

  @Test
  void userRoleEnumCoversTheFourAccessLevels() {
    assertThat(User.Role.values())
        .containsExactly(User.Role.USER, User.Role.EDITOR, User.Role.ADMIN, User.Role.OWNER);
    assertThat(User.Role.valueOf("OWNER")).isEqualTo(User.Role.OWNER);
  }
}
