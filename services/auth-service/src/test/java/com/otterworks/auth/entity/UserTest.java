package com.otterworks.auth.entity;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class UserTest {

  @Test
  void newUserStartsUnverifiedWithoutMfaAndWithoutRoles() {
    User user = new User();

    assertThat(user.isEmailVerified()).isFalse();
    assertThat(user.isMfaEnabled()).isFalse();
    assertThat(user.getMfaSecret()).isNull();
    assertThat(user.getRoles()).isEmpty();
  }

  @Test
  void onCreateStampsBothTimestamps() {
    User user = new User();

    user.onCreate();

    assertThat(user.getCreatedAt()).isNotNull();
    assertThat(user.getUpdatedAt()).isNotNull().isAfterOrEqualTo(user.getCreatedAt());
  }

  @Test
  void onUpdateMovesUpdatedAtForwardWithoutTouchingCreatedAt() throws InterruptedException {
    User user = new User();
    user.onCreate();
    Instant createdAt = user.getCreatedAt();
    Thread.sleep(2);

    user.onUpdate();

    assertThat(user.getCreatedAt()).isEqualTo(createdAt);
    assertThat(user.getUpdatedAt()).isAfter(createdAt);
  }

  @Test
  void mutatorsRoundTripEveryField() {
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
  void roleEnumExposesTheFourApplicationRoles() {
    assertThat(User.Role.values())
        .containsExactly(User.Role.USER, User.Role.EDITOR, User.Role.ADMIN, User.Role.OWNER);
    assertThat(User.Role.valueOf("ADMIN")).isEqualTo(User.Role.ADMIN);
  }
}
