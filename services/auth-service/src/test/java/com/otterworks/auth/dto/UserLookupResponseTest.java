package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.Set;
import java.util.function.Consumer;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class UserLookupResponseTest {

  private static UserLookupResponse base() {
    return new UserLookupResponse("id-1", "user@otterworks.dev", "User One");
  }

  @Test
  void fromUserDTO_keepsOnlyThePublicIdentityFields() {
    UserDTO source =
        new UserDTO(
            "id-1",
            "user@otterworks.dev",
            "User One",
            "https://cdn/avatar.png",
            Set.of("USER", "ADMIN"),
            true,
            Instant.parse("2024-01-01T00:00:00Z"),
            Instant.parse("2024-02-01T00:00:00Z"),
            Instant.parse("2024-03-01T00:00:00Z"));

    UserLookupResponse response = UserLookupResponse.fromUserDTO(source);

    assertThat(response).isEqualTo(base());
    assertThat(response.toString()).doesNotContain("avatar.png").doesNotContain("ADMIN");
  }

  @Test
  void fromUserDTO_propagatesNullFields() {
    UserLookupResponse response = UserLookupResponse.fromUserDTO(new UserDTO());

    assertThat(response.getId()).isNull();
    assertThat(response.getEmail()).isNull();
    assertThat(response.getDisplayName()).isNull();
  }

  @Test
  void settersRoundTrip() {
    UserLookupResponse response = new UserLookupResponse(null, null, null);
    response.setId("id-2");
    response.setEmail("other@otterworks.dev");
    response.setDisplayName("Other");

    assertThat(response).isEqualTo(new UserLookupResponse("id-2", "other@otterworks.dev", "Other"));
  }

  @Test
  void equalValuesAreEqualAndShareHashCode() {
    assertThat(base()).isEqualTo(base()).hasSameHashCodeAs(base());
  }

  @Test
  void equalsIsReflexiveAndRejectsNullAndForeignTypes() {
    UserLookupResponse response = base();

    assertThat(response.equals(response)).isTrue();
    assertThat(response.equals(null)).isFalse();
    assertThat(response.equals("id-1")).isFalse();
  }

  static Stream<Arguments> singleFieldMutations() {
    return Stream.of(
        Arguments.of("id", (Consumer<UserLookupResponse>) r -> r.setId("id-2")),
        Arguments.of("id=null", (Consumer<UserLookupResponse>) r -> r.setId(null)),
        Arguments.of("email", (Consumer<UserLookupResponse>) r -> r.setEmail("x@otterworks.dev")),
        Arguments.of("email=null", (Consumer<UserLookupResponse>) r -> r.setEmail(null)),
        Arguments.of("displayName", (Consumer<UserLookupResponse>) r -> r.setDisplayName("Two")),
        Arguments.of(
            "displayName=null", (Consumer<UserLookupResponse>) r -> r.setDisplayName(null)));
  }

  @ParameterizedTest(name = "differing {0} breaks equality")
  @MethodSource("singleFieldMutations")
  void anySingleDifferingFieldBreaksEquality(String field, Consumer<UserLookupResponse> mutation) {
    UserLookupResponse mutated = base();
    mutation.accept(mutated);

    assertThat(mutated).isNotEqualTo(base());
    assertThat(base()).isNotEqualTo(mutated);
  }

  @Test
  void allNullFieldsCompareEqual() {
    UserLookupResponse left = new UserLookupResponse(null, null, null);
    UserLookupResponse right = new UserLookupResponse(null, null, null);

    assertThat(left).isEqualTo(right).hasSameHashCodeAs(right);
  }

  @Test
  void toStringExposesFieldValues() {
    assertThat(base().toString())
        .contains("id=id-1")
        .contains("email=user@otterworks.dev")
        .contains("displayName=User One");
  }
}
