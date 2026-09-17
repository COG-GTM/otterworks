package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import com.otterworks.auth.entity.UserSettings;
import java.util.function.Consumer;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class UserSettingsDTOTest {

  private static UserSettingsDTO base() {
    return new UserSettingsDTO(true, false, true, "dark", "fr");
  }

  @Test
  void fromEntity_copiesEveryField() {
    UserSettings entity = new UserSettings();
    entity.setNotificationEmail(false);
    entity.setNotificationInApp(true);
    entity.setNotificationDesktop(true);
    entity.setTheme("light");
    entity.setLanguage("de");

    UserSettingsDTO dto = UserSettingsDTO.fromEntity(entity);

    assertThat(dto.isNotificationEmail()).isFalse();
    assertThat(dto.isNotificationInApp()).isTrue();
    assertThat(dto.isNotificationDesktop()).isTrue();
    assertThat(dto.getTheme()).isEqualTo("light");
    assertThat(dto.getLanguage()).isEqualTo("de");
  }

  @Test
  void fromEntity_carriesEntityDefaultsForAFreshEntity() {
    UserSettingsDTO dto = UserSettingsDTO.fromEntity(new UserSettings());

    assertThat(dto).isEqualTo(new UserSettingsDTO(true, true, false, "system", "en"));
  }

  @Test
  void noArgsConstructorLeavesJavaDefaults() {
    UserSettingsDTO dto = new UserSettingsDTO();

    assertThat(dto.isNotificationEmail()).isFalse();
    assertThat(dto.isNotificationInApp()).isFalse();
    assertThat(dto.isNotificationDesktop()).isFalse();
    assertThat(dto.getTheme()).isNull();
    assertThat(dto.getLanguage()).isNull();
  }

  @Test
  void settersRoundTrip() {
    UserSettingsDTO dto = new UserSettingsDTO();
    dto.setNotificationEmail(true);
    dto.setNotificationInApp(true);
    dto.setNotificationDesktop(true);
    dto.setTheme("dark");
    dto.setLanguage("ja");

    assertThat(dto).isEqualTo(new UserSettingsDTO(true, true, true, "dark", "ja"));
  }

  @Test
  void equalValuesAreEqualAndShareHashCode() {
    assertThat(base()).isEqualTo(base()).hasSameHashCodeAs(base());
  }

  @Test
  void equalsIsReflexiveAndRejectsNullAndForeignTypes() {
    UserSettingsDTO dto = base();

    assertThat(dto.equals(dto)).isTrue();
    assertThat(dto.equals(null)).isFalse();
    assertThat(dto.equals("dark")).isFalse();
  }

  static Stream<Arguments> singleFieldMutations() {
    return Stream.of(
        Arguments.of(
            "notificationEmail", (Consumer<UserSettingsDTO>) d -> d.setNotificationEmail(false)),
        Arguments.of(
            "notificationInApp", (Consumer<UserSettingsDTO>) d -> d.setNotificationInApp(true)),
        Arguments.of(
            "notificationDesktop",
            (Consumer<UserSettingsDTO>) d -> d.setNotificationDesktop(false)),
        Arguments.of("theme", (Consumer<UserSettingsDTO>) d -> d.setTheme("light")),
        Arguments.of("theme=null", (Consumer<UserSettingsDTO>) d -> d.setTheme(null)),
        Arguments.of("language", (Consumer<UserSettingsDTO>) d -> d.setLanguage("en")),
        Arguments.of("language=null", (Consumer<UserSettingsDTO>) d -> d.setLanguage(null)));
  }

  @ParameterizedTest(name = "differing {0} breaks equality")
  @MethodSource("singleFieldMutations")
  void anySingleDifferingFieldBreaksEquality(String field, Consumer<UserSettingsDTO> mutation) {
    UserSettingsDTO mutated = base();
    mutation.accept(mutated);

    assertThat(mutated).isNotEqualTo(base());
    assertThat(base()).isNotEqualTo(mutated);
  }

  @Test
  void nullStringFieldsCompareEqualOnBothSides() {
    UserSettingsDTO left = new UserSettingsDTO(true, false, true, null, null);
    UserSettingsDTO right = new UserSettingsDTO(true, false, true, null, null);

    assertThat(left).isEqualTo(right).hasSameHashCodeAs(right);
  }

  @Test
  void toStringExposesFieldValues() {
    assertThat(base().toString())
        .contains("notificationEmail=true")
        .contains("theme=dark")
        .contains("language=fr");
  }
}
