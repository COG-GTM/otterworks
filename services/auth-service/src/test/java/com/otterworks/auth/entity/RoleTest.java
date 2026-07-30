package com.otterworks.auth.entity;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class RoleTest {

  @Test
  void twoArgConstructorPopulatesNameAndDescription() {
    Role role = new Role("ADMIN", "Full administrative access");

    assertThat(role.getId()).isNull();
    assertThat(role.getName()).isEqualTo("ADMIN");
    assertThat(role.getDescription()).isEqualTo("Full administrative access");
  }

  @Test
  void noArgConstructorLeavesEveryFieldUnset() {
    Role role = new Role();

    assertThat(role.getId()).isNull();
    assertThat(role.getName()).isNull();
    assertThat(role.getDescription()).isNull();
  }

  @Test
  void mutatorsRoundTripEveryField() {
    Role role = new Role();

    role.setId(7L);
    role.setName("EDITOR");
    role.setDescription("Can edit documents");

    assertThat(role.getId()).isEqualTo(7L);
    assertThat(role.getName()).isEqualTo("EDITOR");
    assertThat(role.getDescription()).isEqualTo("Can edit documents");
  }
}
