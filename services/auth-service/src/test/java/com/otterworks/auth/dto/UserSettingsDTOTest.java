package com.otterworks.auth.dto;

import static org.assertj.core.api.Assertions.assertThat;

import com.otterworks.auth.entity.UserSettings;
import java.util.function.Consumer;
import org.junit.jupiter.api.Test;

class UserSettingsDTOTest {

  @Test
  void fromEntityCopiesEveryField() {
    UserSettings entity = new UserSettings();
    entity.setNotificationEmail(false);
    entity.setNotificationInApp(false);
    entity.setNotificationDesktop(true);
    entity.setTheme("dark");
    entity.setLanguage("it");

    UserSettingsDTO dto = UserSettingsDTO.fromEntity(entity);

    assertThat(dto.isNotificationEmail()).isFalse();
    assertThat(dto.isNotificationInApp()).isFalse();
    assertThat(dto.isNotificationDesktop()).isTrue();
    assertThat(dto.getTheme()).isEqualTo("dark");
    assertThat(dto.getLanguage()).isEqualTo("it");
  }

  @Test
  void fromEntityMirrorsTheEntityDefaults() {
    UserSettingsDTO dto = UserSettingsDTO.fromEntity(new UserSettings());

    assertThat(dto).isEqualTo(new UserSettingsDTO(true, true, false, "system", "en"));
  }

  @Test
  void noArgConstructorLeavesFlagsFalseAndStringsNull() {
    UserSettingsDTO dto = new UserSettingsDTO();

    assertThat(dto.isNotificationEmail()).isFalse();
    assertThat(dto.isNotificationInApp()).isFalse();
    assertThat(dto.isNotificationDesktop()).isFalse();
    assertThat(dto.getTheme()).isNull();
    assertThat(dto.getLanguage()).isNull();
  }

  @Test
  void mutatorsRoundTripEveryField() {
    UserSettingsDTO dto = new UserSettingsDTO();

    dto.setNotificationEmail(true);
    dto.setNotificationInApp(true);
    dto.setNotificationDesktop(true);
    dto.setTheme("light");
    dto.setLanguage("pt");

    assertThat(dto).isEqualTo(new UserSettingsDTO(true, true, true, "light", "pt"));
  }

  @Test
  void valueSemanticsTreatIdenticalPayloadsAsEqual() {
    assertThat(full()).isEqualTo(full()).hasSameHashCodeAs(full());
    UserSettingsDTO dto = full();
    assertThat(dto).isEqualTo(dto).isNotEqualTo(null).isNotEqualTo("dark");
    assertThat(dto.toString()).contains("dark", "it");
  }

  @Test
  void anyDifferingFieldBreaksEquality() {
    assertThat(mutate(d -> d.setNotificationEmail(true))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setNotificationInApp(true))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setNotificationDesktop(false))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setTheme("light"))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setLanguage("en"))).isNotEqualTo(full());
    assertThat(mutate(d -> d.setTheme(null))).isNotEqualTo(full());
    assertThat(full()).isNotEqualTo(mutate(d -> d.setTheme(null)));
    assertThat(mutate(d -> d.setLanguage(null))).isNotEqualTo(full());
    assertThat(new UserSettingsDTO().hashCode()).isNotEqualTo(full().hashCode());
  }

  private static UserSettingsDTO full() {
    return new UserSettingsDTO(false, false, true, "dark", "it");
  }

  private static UserSettingsDTO mutate(Consumer<UserSettingsDTO> change) {
    UserSettingsDTO dto = full();
    change.accept(dto);
    return dto;
  }
}
