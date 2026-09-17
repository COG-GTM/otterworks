package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import com.otterworks.auth.entity.User;
import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import java.util.function.Consumer;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class UserDTOTest {

  private static final Instant CREATED = Instant.parse("2024-01-01T00:00:00Z");
  private static final Instant UPDATED = Instant.parse("2024-02-01T00:00:00Z");
  private static final Instant LAST_LOGIN = Instant.parse("2024-03-01T00:00:00Z");

  private static UserDTO base() {
    return new UserDTO(
        "id-1",
        "user@otterworks.dev",
        "User One",
        "https://cdn/avatar.png",
        Set.of("USER"),
        true,
        CREATED,
        UPDATED,
        LAST_LOGIN);
  }

  @Test
  void fromEntity_mapsEveryFieldAndStringifiesRoles() {
    UUID id = UUID.randomUUID();
    User user = new User();
    user.setId(id);
    user.setEmail("user@otterworks.dev");
    user.setDisplayName("User One");
    user.setAvatarUrl("https://cdn/avatar.png");
    user.setRoles(Set.of(User.Role.USER, User.Role.ADMIN));
    user.setEmailVerified(true);
    user.setCreatedAt(CREATED);
    user.setUpdatedAt(UPDATED);
    user.setLastLoginAt(LAST_LOGIN);

    UserDTO dto = UserDTO.fromEntity(user);

    assertThat(dto.getId()).isEqualTo(id.toString());
    assertThat(dto.getEmail()).isEqualTo("user@otterworks.dev");
    assertThat(dto.getDisplayName()).isEqualTo("User One");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn/avatar.png");
    assertThat(dto.getRoles()).containsExactlyInAnyOrder("USER", "ADMIN");
    assertThat(dto.isEmailVerified()).isTrue();
    assertThat(dto.getCreatedAt()).isEqualTo(CREATED);
    assertThat(dto.getUpdatedAt()).isEqualTo(UPDATED);
    assertThat(dto.getLastLoginAt()).isEqualTo(LAST_LOGIN);
  }

  @Test
  void fromEntity_neverLeaksThePasswordHash() {
    User user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("user@otterworks.dev");
    user.setDisplayName("User One");
    user.setPasswordHash("$2a$12$averysecrethash");
    user.setRoles(Set.of(User.Role.USER));

    UserDTO dto = UserDTO.fromEntity(user);

    assertThat(dto.toString()).doesNotContain("averysecrethash");
  }

  @Test
  void fromEntity_toleratesAnUnverifiedUserThatNeverLoggedIn() {
    User user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("fresh@otterworks.dev");
    user.setDisplayName("Fresh");
    user.setRoles(Set.of());

    UserDTO dto = UserDTO.fromEntity(user);

    assertThat(dto.getRoles()).isEmpty();
    assertThat(dto.isEmailVerified()).isFalse();
    assertThat(dto.getAvatarUrl()).isNull();
    assertThat(dto.getLastLoginAt()).isNull();
  }

  @Test
  void settersRoundTrip() {
    UserDTO dto = new UserDTO();
    dto.setId("id-1");
    dto.setEmail("user@otterworks.dev");
    dto.setDisplayName("User One");
    dto.setAvatarUrl("https://cdn/avatar.png");
    dto.setRoles(Set.of("USER"));
    dto.setEmailVerified(true);
    dto.setCreatedAt(CREATED);
    dto.setUpdatedAt(UPDATED);
    dto.setLastLoginAt(LAST_LOGIN);

    assertThat(dto).isEqualTo(base()).hasSameHashCodeAs(base());
  }

  @Test
  void equalsIsReflexiveAndRejectsNullAndForeignTypes() {
    UserDTO dto = base();

    assertThat(dto.equals(dto)).isTrue();
    assertThat(dto.equals(null)).isFalse();
    assertThat(dto.equals("id-1")).isFalse();
  }

  static Stream<Arguments> singleFieldMutations() {
    return Stream.of(
        Arguments.of("id", (Consumer<UserDTO>) d -> d.setId("id-2")),
        Arguments.of("id=null", (Consumer<UserDTO>) d -> d.setId(null)),
        Arguments.of("email", (Consumer<UserDTO>) d -> d.setEmail("other@otterworks.dev")),
        Arguments.of("email=null", (Consumer<UserDTO>) d -> d.setEmail(null)),
        Arguments.of("displayName", (Consumer<UserDTO>) d -> d.setDisplayName("Other")),
        Arguments.of("displayName=null", (Consumer<UserDTO>) d -> d.setDisplayName(null)),
        Arguments.of("avatarUrl", (Consumer<UserDTO>) d -> d.setAvatarUrl("https://cdn/other.png")),
        Arguments.of("avatarUrl=null", (Consumer<UserDTO>) d -> d.setAvatarUrl(null)),
        Arguments.of("roles", (Consumer<UserDTO>) d -> d.setRoles(Set.of("ADMIN"))),
        Arguments.of("roles=null", (Consumer<UserDTO>) d -> d.setRoles(null)),
        Arguments.of("emailVerified", (Consumer<UserDTO>) d -> d.setEmailVerified(false)),
        Arguments.of("createdAt", (Consumer<UserDTO>) d -> d.setCreatedAt(UPDATED)),
        Arguments.of("createdAt=null", (Consumer<UserDTO>) d -> d.setCreatedAt(null)),
        Arguments.of("updatedAt", (Consumer<UserDTO>) d -> d.setUpdatedAt(CREATED)),
        Arguments.of("updatedAt=null", (Consumer<UserDTO>) d -> d.setUpdatedAt(null)),
        Arguments.of("lastLoginAt", (Consumer<UserDTO>) d -> d.setLastLoginAt(CREATED)),
        Arguments.of("lastLoginAt=null", (Consumer<UserDTO>) d -> d.setLastLoginAt(null)));
  }

  @ParameterizedTest(name = "differing {0} breaks equality")
  @MethodSource("singleFieldMutations")
  void anySingleDifferingFieldBreaksEquality(String field, Consumer<UserDTO> mutation) {
    UserDTO mutated = base();
    mutation.accept(mutated);

    assertThat(mutated).isNotEqualTo(base());
    assertThat(base()).isNotEqualTo(mutated);
  }

  @Test
  void twoEmptyDtosAreEqual() {
    assertThat(new UserDTO()).isEqualTo(new UserDTO()).hasSameHashCodeAs(new UserDTO());
  }

  @Test
  void toStringExposesFieldValues() {
    assertThat(base().toString())
        .contains("id=id-1")
        .contains("email=user@otterworks.dev")
        .contains("emailVerified=true");
  }
}
