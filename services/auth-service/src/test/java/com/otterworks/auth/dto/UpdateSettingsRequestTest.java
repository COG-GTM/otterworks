package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.function.Consumer;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class UpdateSettingsRequestTest {

  private static UpdateSettingsRequest base() {
    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setNotificationEmail(true);
    request.setNotificationInApp(false);
    request.setNotificationDesktop(true);
    request.setTheme("dark");
    request.setLanguage("fr");
    return request;
  }

  @Test
  void everyFieldStartsNullSoPartialUpdatesAreDistinguishable() {
    UpdateSettingsRequest request = new UpdateSettingsRequest();

    assertThat(request.getNotificationEmail()).isNull();
    assertThat(request.getNotificationInApp()).isNull();
    assertThat(request.getNotificationDesktop()).isNull();
    assertThat(request.getTheme()).isNull();
    assertThat(request.getLanguage()).isNull();
  }

  @Test
  void settersRoundTrip() {
    UpdateSettingsRequest request = base();

    assertThat(request.getNotificationEmail()).isTrue();
    assertThat(request.getNotificationInApp()).isFalse();
    assertThat(request.getNotificationDesktop()).isTrue();
    assertThat(request.getTheme()).isEqualTo("dark");
    assertThat(request.getLanguage()).isEqualTo("fr");
  }

  @Test
  void equalValuesAreEqualAndShareHashCode() {
    assertThat(base()).isEqualTo(base()).hasSameHashCodeAs(base());
  }

  @Test
  void equalsIsReflexiveAndRejectsNullAndForeignTypes() {
    UpdateSettingsRequest request = base();

    assertThat(request.equals(request)).isTrue();
    assertThat(request.equals(null)).isFalse();
    assertThat(request.equals("dark")).isFalse();
  }

  static Stream<Arguments> singleFieldMutations() {
    return Stream.of(
        Arguments.of(
            "notificationEmail",
            (Consumer<UpdateSettingsRequest>) r -> r.setNotificationEmail(false)),
        Arguments.of(
            "notificationEmail=null",
            (Consumer<UpdateSettingsRequest>) r -> r.setNotificationEmail(null)),
        Arguments.of(
            "notificationInApp",
            (Consumer<UpdateSettingsRequest>) r -> r.setNotificationInApp(true)),
        Arguments.of(
            "notificationInApp=null",
            (Consumer<UpdateSettingsRequest>) r -> r.setNotificationInApp(null)),
        Arguments.of(
            "notificationDesktop",
            (Consumer<UpdateSettingsRequest>) r -> r.setNotificationDesktop(false)),
        Arguments.of(
            "notificationDesktop=null",
            (Consumer<UpdateSettingsRequest>) r -> r.setNotificationDesktop(null)),
        Arguments.of("theme", (Consumer<UpdateSettingsRequest>) r -> r.setTheme("light")),
        Arguments.of("theme=null", (Consumer<UpdateSettingsRequest>) r -> r.setTheme(null)),
        Arguments.of("language", (Consumer<UpdateSettingsRequest>) r -> r.setLanguage("en")),
        Arguments.of("language=null", (Consumer<UpdateSettingsRequest>) r -> r.setLanguage(null)));
  }

  @ParameterizedTest(name = "differing {0} breaks equality")
  @MethodSource("singleFieldMutations")
  void anySingleDifferingFieldBreaksEquality(
      String field, Consumer<UpdateSettingsRequest> mutation) {
    UpdateSettingsRequest mutated = base();
    mutation.accept(mutated);

    assertThat(mutated).isNotEqualTo(base());
    assertThat(base()).isNotEqualTo(mutated);
  }

  @Test
  void twoEmptyRequestsAreEqual() {
    assertThat(new UpdateSettingsRequest())
        .isEqualTo(new UpdateSettingsRequest())
        .hasSameHashCodeAs(new UpdateSettingsRequest());
  }

  @Test
  void toStringExposesFieldValues() {
    assertThat(base().toString())
        .contains("notificationEmail=true")
        .contains("notificationInApp=false")
        .contains("theme=dark")
        .contains("language=fr");
  }
}
