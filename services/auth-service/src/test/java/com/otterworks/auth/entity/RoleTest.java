package com.otterworks.auth.entity;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class RoleTest {

  @Test
  void noArgsConstructorLeavesEveryFieldUnset() {
    Role role = new Role();

    assertThat(role.getId()).isNull();
    assertThat(role.getName()).isNull();
    assertThat(role.getDescription()).isNull();
  }

  @Test
  void twoArgConstructorSetsNameAndDescriptionButNotTheGeneratedId() {
    Role role = new Role("ADMIN", "Full administrative access");

    assertThat(role.getName()).isEqualTo("ADMIN");
    assertThat(role.getDescription()).isEqualTo("Full administrative access");
    assertThat(role.getId()).isNull();
  }

  @Test
  void settersRoundTrip() {
    Role role = new Role();
    role.setId(42L);
    role.setName("EDITOR");
    role.setDescription("Can edit documents");

    assertThat(role.getId()).isEqualTo(42L);
    assertThat(role.getName()).isEqualTo("EDITOR");
    assertThat(role.getDescription()).isEqualTo("Can edit documents");
  }

  @Test
  void aNullDescriptionIsAllowedBecauseTheColumnIsOptional() {
    Role role = new Role("USER", null);

    assertThat(role.getName()).isEqualTo("USER");
    assertThat(role.getDescription()).isNull();
  }
}
