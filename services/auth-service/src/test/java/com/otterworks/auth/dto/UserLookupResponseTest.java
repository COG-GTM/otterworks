package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.Set;
import java.util.function.Consumer;
import org.junit.jupiter.api.Test;

class UserLookupResponseTest {

  @Test
  void fromUserDtoKeepsOnlyThePublicIdentityFields() {
    UserDTO source =
        new UserDTO(
            "id-1",
            "lookup@otterworks.dev",
            "Lookup User",
            "https://cdn.otterworks.dev/l.png",
            Set.of("USER"),
            true,
            Instant.parse("2024-01-01T00:00:00Z"),
            Instant.parse("2024-01-02T00:00:00Z"),
            Instant.parse("2024-01-03T00:00:00Z"));

    UserLookupResponse response = UserLookupResponse.fromUserDTO(source);

    assertThat(response.getId()).isEqualTo("id-1");
    assertThat(response.getEmail()).isEqualTo("lookup@otterworks.dev");
    assertThat(response.getDisplayName()).isEqualTo("Lookup User");
    assertThat(response.toString()).doesNotContain("cdn.otterworks.dev", "USER");
  }

  @Test
  void fromUserDtoPropagatesNulls() {
    UserLookupResponse response = UserLookupResponse.fromUserDTO(new UserDTO());

    assertThat(response.getId()).isNull();
    assertThat(response.getEmail()).isNull();
    assertThat(response.getDisplayName()).isNull();
  }

  @Test
  void mutatorsRoundTripEveryField() {
    UserLookupResponse response = new UserLookupResponse("a", "b", "c");

    response.setId("id-2");
    response.setEmail("changed@otterworks.dev");
    response.setDisplayName("Changed");

    assertThat(response)
        .isEqualTo(new UserLookupResponse("id-2", "changed@otterworks.dev", "Changed"));
  }

  @Test
  void valueSemanticsTreatIdenticalPayloadsAsEqual() {
    assertThat(full()).isEqualTo(full()).hasSameHashCodeAs(full());
    UserLookupResponse response = full();
    assertThat(response).isEqualTo(response).isNotEqualTo(null).isNotEqualTo("id-1");
  }

  @Test
  void anyDifferingFieldBreaksEquality() {
    assertThat(mutate(r -> r.setId("other"))).isNotEqualTo(full());
    assertThat(mutate(r -> r.setEmail("other@otterworks.dev"))).isNotEqualTo(full());
    assertThat(mutate(r -> r.setDisplayName("Other"))).isNotEqualTo(full());
    assertThat(mutate(r -> r.setId(null))).isNotEqualTo(full());
    assertThat(full()).isNotEqualTo(mutate(r -> r.setId(null)));
    assertThat(mutate(r -> r.setEmail(null))).isNotEqualTo(full());
    assertThat(mutate(r -> r.setDisplayName(null))).isNotEqualTo(full());
    assertThat(new UserLookupResponse(null, null, null).hashCode()).isNotEqualTo(full().hashCode());
  }

  private static UserLookupResponse full() {
    return new UserLookupResponse("id-1", "lookup@otterworks.dev", "Lookup User");
  }

  private static UserLookupResponse mutate(Consumer<UserLookupResponse> change) {
    UserLookupResponse response = full();
    change.accept(response);
    return response;
  }
}
