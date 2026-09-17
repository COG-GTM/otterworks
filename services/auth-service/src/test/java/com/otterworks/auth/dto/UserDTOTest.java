package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import com.otterworks.auth.entity.User;
import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import java.util.function.Consumer;
import org.junit.jupiter.api.Test;

class UserDTOTest {

  private static final Instant CREATED = Instant.parse("2024-01-01T00:00:00Z");
  private static final Instant UPDATED = Instant.parse("2024-02-01T00:00:00Z");
  private static final Instant LAST_LOGIN = Instant.parse("2024-03-01T00:00:00Z");

  @Test
  void fromEntityCopiesEveryFieldAndRendersRolesAsNames() {
    UUID id = UUID.randomUUID();
    User user = new User();
    user.setId(id);
    user.setEmail("dto@otterworks.dev");
    user.setDisplayName("Dto User");
    user.setAvatarUrl("https://cdn.otterworks.dev/d.png");
    user.setEmailVerified(true);
    user.setRoles(Set.of(User.Role.USER, User.Role.ADMIN));
    user.setLastLoginAt(LAST_LOGIN);

    UserDTO dto = UserDTO.fromEntity(user);

    assertThat(dto.getId()).isEqualTo(id.toString());
    assertThat(dto.getEmail()).isEqualTo("dto@otterworks.dev");
    assertThat(dto.getDisplayName()).isEqualTo("Dto User");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/d.png");
    assertThat(dto.isEmailVerified()).isTrue();
    assertThat(dto.getRoles()).containsExactlyInAnyOrder("USER", "ADMIN");
    assertThat(dto.getLastLoginAt()).isEqualTo(LAST_LOGIN);
  }

  @Test
  void fromEntityKeepsOptionalFieldsNull() {
    User user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("minimal@otterworks.dev");
    user.setDisplayName("Minimal");

    UserDTO dto = UserDTO.fromEntity(user);

    assertThat(dto.getAvatarUrl()).isNull();
    assertThat(dto.getCreatedAt()).isNull();
    assertThat(dto.getUpdatedAt()).isNull();
    assertThat(dto.getLastLoginAt()).isNull();
    assertThat(dto.getRoles()).isEmpty();
    assertThat(dto.isEmailVerified()).isFalse();
  }

  @Test
  void allArgsConstructorAndAccessorsAgree() {
    UserDTO dto =
        new UserDTO(
            "id-1",
            "a@b.dev",
            "Name",
            "avatar",
            Set.of("USER"),
            true,
            CREATED,
            UPDATED,
            LAST_LOGIN);

    assertThat(dto.getId()).isEqualTo("id-1");
    assertThat(dto.getEmail()).isEqualTo("a@b.dev");
    assertThat(dto.getDisplayName()).isEqualTo("Name");
    assertThat(dto.getAvatarUrl()).isEqualTo("avatar");
    assertThat(dto.getRoles()).containsExactly("USER");
    assertThat(dto.isEmailVerified()).isTrue();
    assertThat(dto.getCreatedAt()).isEqualTo(CREATED);
    assertThat(dto.getUpdatedAt()).isEqualTo(UPDATED);
  }

  @Test
  void valueSemanticsTreatIdenticalPayloadsAsEqual() {
    assertThat(full()).isEqualTo(full()).hasSameHashCodeAs(full());
    assertThat(new UserDTO()).isEqualTo(new UserDTO()).hasSameHashCodeAs(new UserDTO());
    UserDTO dto = full();
    assertThat(dto).isEqualTo(dto).isNotEqualTo(null).isNotEqualTo("id-1");
    assertThat(dto.toString()).contains("dto@otterworks.dev", "Dto User");
  }

  @Test
  void anyDifferingFieldBreaksEquality() {
    assertThat(mutate(d -> d.setId("other"))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setEmail("other@otterworks.dev"))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setDisplayName("Other"))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setAvatarUrl("other"))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setRoles(Set.of("ADMIN")))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setEmailVerified(false))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setCreatedAt(UPDATED))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setUpdatedAt(CREATED))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setLastLoginAt(CREATED))).isNotEqualTo(full());
  }

  @Test
  void nullFieldsNeverEqualPopulatedOnes() {
    assertThat(mutate(d -> d.setId(null))).isNotEqualTo(full());
    assertThat(full()).isNotEqualTo(mutate(d -> d.setId(null)));
    assertThat(mutate(d -> d.setEmail(null))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setDisplayName(null))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setAvatarUrl(null))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setRoles(null))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setCreatedAt(null))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setUpdatedAt(null))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setLastLoginAt(null))).isNotEqualTo(full());
    assertThat(new UserDTO().hashCode()).isNotEqualTo(full().hashCode());
  }

  private static UserDTO full() {
    return new UserDTO(
        "id-1",
        "dto@otterworks.dev",
        "Dto User",
        "avatar",
        Set.of("USER"),
        true,
        CREATED,
        UPDATED,
        LAST_LOGIN);
  }

  private static UserDTO mutate(Consumer<UserDTO> change) {
    UserDTO dto = full();
    change.accept(dto);
    return dto;
  }
}
