package com.otterworks.auth.entity;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.UUID;
import org.junit.jupiter.api.Test;

class UserSettingsTest {

  @Test
  void defaultsOptInToEmailAndInAppButNotDesktopNotifications() {
    UserSettings settings = new UserSettings();

    assertThat(settings.isNotificationEmail()).isTrue();
    assertThat(settings.isNotificationInApp()).isTrue();
    assertThat(settings.isNotificationDesktop()).isFalse();
    assertThat(settings.getTheme()).isEqualTo("system");
    assertThat(settings.getLanguage()).isEqualTo("en");
    assertThat(settings.getUserId()).isNull();
    assertThat(settings.getUser()).isNull();
  }

  @Test
  void settersRoundTrip() {
    UUID userId = UUID.randomUUID();
    User user = new User();
    user.setId(userId);

    UserSettings settings = new UserSettings();
    settings.setUserId(userId);
    settings.setUser(user);
    settings.setNotificationEmail(false);
    settings.setNotificationInApp(false);
    settings.setNotificationDesktop(true);
    settings.setTheme("dark");
    settings.setLanguage("fr");

    assertThat(settings.getUserId()).isEqualTo(userId);
    assertThat(settings.getUser()).isSameAs(user);
    assertThat(settings.isNotificationEmail()).isFalse();
    assertThat(settings.isNotificationInApp()).isFalse();
    assertThat(settings.isNotificationDesktop()).isTrue();
    assertThat(settings.getTheme()).isEqualTo("dark");
    assertThat(settings.getLanguage()).isEqualTo("fr");
  }

  @Test
  void settingTheOwnerDoesNotItselfPopulateTheMappedId() {
    User user = new User();
    user.setId(UUID.randomUUID());

    UserSettings settings = new UserSettings();
    settings.setUser(user);

    assertThat(settings.getUserId()).isNull();
  }
}
