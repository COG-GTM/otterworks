package com.otterworks.auth.entity;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class UserTest {

  @Test
  void aFreshUserIsUnverifiedWithoutMfaAndWithNoRoles() {
    User user = new User();

    assertThat(user.isEmailVerified()).isFalse();
    assertThat(user.isMfaEnabled()).isFalse();
    assertThat(user.getMfaSecret()).isNull();
    assertThat(user.getRoles()).isEmpty();
    assertThat(user.getCreatedAt()).isNull();
    assertThat(user.getUpdatedAt()).isNull();
    assertThat(user.getLastLoginAt()).isNull();
  }

  @Test
  void settersRoundTrip() {
    UUID id = UUID.randomUUID();
    Instant lastLogin = Instant.parse("2024-03-01T00:00:00Z");
    User user = new User();
    user.setId(id);
    user.setEmail("user@otterworks.dev");
    user.setPasswordHash("$2a$12$hash");
    user.setDisplayName("User One");
    user.setAvatarUrl("https://cdn/avatar.png");
    user.setEmailVerified(true);
    user.setMfaEnabled(true);
    user.setMfaSecret("secret");
    user.setRoles(Set.of(User.Role.ADMIN));
    user.setLastLoginAt(lastLogin);

    assertThat(user.getId()).isEqualTo(id);
    assertThat(user.getEmail()).isEqualTo("user@otterworks.dev");
    assertThat(user.getPasswordHash()).isEqualTo("$2a$12$hash");
    assertThat(user.getDisplayName()).isEqualTo("User One");
    assertThat(user.getAvatarUrl()).isEqualTo("https://cdn/avatar.png");
    assertThat(user.isEmailVerified()).isTrue();
    assertThat(user.isMfaEnabled()).isTrue();
    assertThat(user.getMfaSecret()).isEqualTo("secret");
    assertThat(user.getRoles()).containsExactly(User.Role.ADMIN);
    assertThat(user.getLastLoginAt()).isEqualTo(lastLogin);
  }

  @Test
  void onCreateStampsBothTimestampsToTheSameInstant() {
    User user = new User();
    Instant before = Instant.now();

    user.onCreate();

    assertThat(user.getCreatedAt()).isNotNull().isAfterOrEqualTo(before);
    assertThat(user.getUpdatedAt()).isNotNull().isAfterOrEqualTo(before);
  }

  @Test
  void onUpdateAdvancesUpdatedAtAndLeavesCreatedAtUntouched() {
    User user = new User();
    Instant created = Instant.parse("2020-01-01T00:00:00Z");
    user.setCreatedAt(created);
    user.setUpdatedAt(created);

    user.onUpdate();

    assertThat(user.getCreatedAt()).isEqualTo(created);
    assertThat(user.getUpdatedAt()).isAfter(created);
  }

  @Test
  void theRoleEnumDeclaresTheFourApplicationRoles() {
    assertThat(User.Role.values())
        .containsExactly(User.Role.USER, User.Role.EDITOR, User.Role.ADMIN, User.Role.OWNER);
    assertThat(User.Role.valueOf("OWNER")).isEqualTo(User.Role.OWNER);
  }
}
