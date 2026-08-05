package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.function.Consumer;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class AuthResponseTest {

  private static AuthResponse.UserDto baseUser() {
    return new AuthResponse.UserDto(
        "id-1", "user@otterworks.dev", "User One", "https://cdn/avatar.png");
  }

  private static AuthResponse base() {
    return new AuthResponse("access", "refresh", "Bearer", 3600L, baseUser());
  }

  @Test
  void allArgsConstructorExposesEveryField() {
    AuthResponse response = base();

    assertThat(response.getAccessToken()).isEqualTo("access");
    assertThat(response.getRefreshToken()).isEqualTo("refresh");
    assertThat(response.getTokenType()).isEqualTo("Bearer");
    assertThat(response.getExpiresIn()).isEqualTo(3600L);
    assertThat(response.getUser().getEmail()).isEqualTo("user@otterworks.dev");
    assertThat(response.getUser().getId()).isEqualTo("id-1");
    assertThat(response.getUser().getDisplayName()).isEqualTo("User One");
    assertThat(response.getUser().getAvatarUrl()).isEqualTo("https://cdn/avatar.png");
  }

  @Test
  void settersRoundTrip() {
    AuthResponse response = new AuthResponse(null, null, null, 0L, null);
    response.setAccessToken("access");
    response.setRefreshToken("refresh");
    response.setTokenType("Bearer");
    response.setExpiresIn(3600L);
    response.setUser(baseUser());

    assertThat(response).isEqualTo(base()).hasSameHashCodeAs(base());
  }

  @Test
  void equalsIsReflexiveAndRejectsNullAndForeignTypes() {
    AuthResponse response = base();

    assertThat(response.equals(response)).isTrue();
    assertThat(response.equals(null)).isFalse();
    assertThat(response.equals("access")).isFalse();
  }

  static Stream<Arguments> singleFieldMutations() {
    return Stream.of(
        Arguments.of("accessToken", (Consumer<AuthResponse>) r -> r.setAccessToken("other")),
        Arguments.of("accessToken=null", (Consumer<AuthResponse>) r -> r.setAccessToken(null)),
        Arguments.of("refreshToken", (Consumer<AuthResponse>) r -> r.setRefreshToken("other")),
        Arguments.of("refreshToken=null", (Consumer<AuthResponse>) r -> r.setRefreshToken(null)),
        Arguments.of("tokenType", (Consumer<AuthResponse>) r -> r.setTokenType("Basic")),
        Arguments.of("tokenType=null", (Consumer<AuthResponse>) r -> r.setTokenType(null)),
        Arguments.of("expiresIn", (Consumer<AuthResponse>) r -> r.setExpiresIn(60L)),
        Arguments.of("user=null", (Consumer<AuthResponse>) r -> r.setUser(null)),
        Arguments.of(
            "user",
            (Consumer<AuthResponse>)
                r ->
                    r.setUser(
                        new AuthResponse.UserDto("id-2", "b@otterworks.dev", "Two", "https://x"))));
  }

  @ParameterizedTest(name = "differing {0} breaks equality")
  @MethodSource("singleFieldMutations")
  void anySingleDifferingFieldBreaksEquality(String field, Consumer<AuthResponse> mutation) {
    AuthResponse mutated = base();
    mutation.accept(mutated);

    assertThat(mutated).isNotEqualTo(base());
    assertThat(base()).isNotEqualTo(mutated);
  }

  @Test
  void nullTokensCompareEqualOnBothSides() {
    AuthResponse left = new AuthResponse(null, null, null, 0L, null);
    AuthResponse right = new AuthResponse(null, null, null, 0L, null);

    assertThat(left).isEqualTo(right).hasSameHashCodeAs(right);
  }

  @Test
  void userDtoEqualsIsReflexiveAndRejectsNullAndForeignTypes() {
    AuthResponse.UserDto user = baseUser();

    assertThat(user.equals(user)).isTrue();
    assertThat(user.equals(null)).isFalse();
    assertThat(user.equals("id-1")).isFalse();
    assertThat(user).isEqualTo(baseUser()).hasSameHashCodeAs(baseUser());
  }

  static Stream<Arguments> singleUserFieldMutations() {
    return Stream.of(
        Arguments.of("id", (Consumer<AuthResponse.UserDto>) u -> u.setId("id-2")),
        Arguments.of("id=null", (Consumer<AuthResponse.UserDto>) u -> u.setId(null)),
        Arguments.of("email", (Consumer<AuthResponse.UserDto>) u -> u.setEmail("b@otterworks.dev")),
        Arguments.of("email=null", (Consumer<AuthResponse.UserDto>) u -> u.setEmail(null)),
        Arguments.of("displayName", (Consumer<AuthResponse.UserDto>) u -> u.setDisplayName("Two")),
        Arguments.of(
            "displayName=null", (Consumer<AuthResponse.UserDto>) u -> u.setDisplayName(null)),
        Arguments.of(
            "avatarUrl", (Consumer<AuthResponse.UserDto>) u -> u.setAvatarUrl("https://cdn/2.png")),
        Arguments.of("avatarUrl=null", (Consumer<AuthResponse.UserDto>) u -> u.setAvatarUrl(null)));
  }

  @ParameterizedTest(name = "differing user.{0} breaks equality")
  @MethodSource("singleUserFieldMutations")
  void anySingleDifferingUserFieldBreaksEquality(
      String field, Consumer<AuthResponse.UserDto> mutation) {
    AuthResponse.UserDto mutated = baseUser();
    mutation.accept(mutated);

    assertThat(mutated).isNotEqualTo(baseUser());
    assertThat(baseUser()).isNotEqualTo(mutated);
  }

  @Test
  void userDtoWithAllNullFieldsCompareEqual() {
    AuthResponse.UserDto left = new AuthResponse.UserDto(null, null, null, null);
    AuthResponse.UserDto right = new AuthResponse.UserDto(null, null, null, null);

    assertThat(left).isEqualTo(right).hasSameHashCodeAs(right);
  }

  @Test
  void toStringExposesTokenMetadata() {
    assertThat(base().toString()).contains("tokenType=Bearer").contains("expiresIn=3600");
    assertThat(baseUser().toString()).contains("email=user@otterworks.dev");
  }
}
