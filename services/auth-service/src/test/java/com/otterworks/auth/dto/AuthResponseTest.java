package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.function.Consumer;
import org.junit.jupiter.api.Test;

class AuthResponseTest {

  @Test
  void accessorsExposeTheConstructorArguments() {
    AuthResponse response = full();

    assertThat(response.getAccessToken()).isEqualTo("access");
    assertThat(response.getRefreshToken()).isEqualTo("refresh");
    assertThat(response.getTokenType()).isEqualTo("Bearer");
    assertThat(response.getExpiresIn()).isEqualTo(3600L);
    assertThat(response.getUser().getId()).isEqualTo("id-1");
    assertThat(response.getUser().getEmail()).isEqualTo("auth@otterworks.dev");
    assertThat(response.getUser().getDisplayName()).isEqualTo("Auth User");
    assertThat(response.getUser().getAvatarUrl()).isNull();
  }

  @Test
  void mutatorsRoundTripEveryField() {
    AuthResponse response = full();
    AuthResponse.UserDto user = new AuthResponse.UserDto("id-2", "b@c.dev", "B", "avatar");

    response.setAccessToken("a2");
    response.setRefreshToken("r2");
    response.setTokenType("MAC");
    response.setExpiresIn(60L);
    response.setUser(user);

    assertThat(response).isEqualTo(new AuthResponse("a2", "r2", "MAC", 60L, user));
  }

  @Test
  void userDtoMutatorsRoundTripEveryField() {
    AuthResponse.UserDto user = new AuthResponse.UserDto("id-1", "a@b.dev", "A", null);

    user.setId("id-9");
    user.setEmail("z@b.dev");
    user.setDisplayName("Z");
    user.setAvatarUrl("https://cdn.otterworks.dev/z.png");

    assertThat(user)
        .isEqualTo(
            new AuthResponse.UserDto("id-9", "z@b.dev", "Z", "https://cdn.otterworks.dev/z.png"));
  }

  @Test
  void valueSemanticsTreatIdenticalPayloadsAsEqual() {
    assertThat(full()).isEqualTo(full()).hasSameHashCodeAs(full());
    AuthResponse response = full();
    assertThat(response).isEqualTo(response).isNotEqualTo(null).isNotEqualTo("access");
    assertThat(response.toString()).contains("access", "refresh", "Bearer");
  }

  @Test
  void anyDifferingFieldBreaksEquality() {
    assertThat(mutate(r -> r.setAccessToken("other"))).isNotEqualTo(full());
    assertThat(mutate(r -> r.setRefreshToken("other"))).isNotEqualTo(full());
    assertThat(mutate(r -> r.setTokenType("MAC"))).isNotEqualTo(full());
    assertThat(mutate(r -> r.setExpiresIn(1L))).isNotEqualTo(full());
    assertThat(mutate(r -> r.setUser(null))).isNotEqualTo(full());
    assertThat(full()).isNotEqualTo(mutate(r -> r.setUser(null)));
    assertThat(mutate(r -> r.setAccessToken(null))).isNotEqualTo(full());
    assertThat(mutate(r -> r.setRefreshToken(null))).isNotEqualTo(full());
    assertThat(mutate(r -> r.setTokenType(null))).isNotEqualTo(full());
    assertThat(new AuthResponse(null, null, null, 0L, null).hashCode())
        .isNotEqualTo(full().hashCode());
  }

  @Test
  void nestedUserDtoValueSemantics() {
    AuthResponse.UserDto user = new AuthResponse.UserDto("id-1", "a@b.dev", "A", "avatar");

    assertThat(user)
        .isEqualTo(new AuthResponse.UserDto("id-1", "a@b.dev", "A", "avatar"))
        .hasSameHashCodeAs(new AuthResponse.UserDto("id-1", "a@b.dev", "A", "avatar"))
        .isNotEqualTo(new AuthResponse.UserDto("id-2", "a@b.dev", "A", "avatar"))
        .isNotEqualTo(new AuthResponse.UserDto("id-1", "z@b.dev", "A", "avatar"))
        .isNotEqualTo(new AuthResponse.UserDto("id-1", "a@b.dev", "Z", "avatar"))
        .isNotEqualTo(new AuthResponse.UserDto("id-1", "a@b.dev", "A", null))
        .isNotEqualTo(null)
        .isNotEqualTo("id-1");
    assertThat(new AuthResponse.UserDto(null, null, null, null))
        .isEqualTo(new AuthResponse.UserDto(null, null, null, null))
        .isNotEqualTo(user);
    assertThat(user.toString()).contains("id-1", "a@b.dev");
  }

  private static AuthResponse full() {
    return new AuthResponse(
        "access",
        "refresh",
        "Bearer",
        3600L,
        new AuthResponse.UserDto("id-1", "auth@otterworks.dev", "Auth User", null));
  }

  private static AuthResponse mutate(Consumer<AuthResponse> change) {
    AuthResponse response = full();
    change.accept(response);
    return response;
  }
}
