package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.otterworks.auth.dto.UpdateSettingsRequest;
import com.otterworks.auth.dto.UserSettingsDTO;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.entity.UserSettings;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.repository.UserSettingsRepository;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class UserSettingsServiceTest {

  @Mock private UserSettingsRepository settingsRepository;
  @Mock private UserRepository userRepository;

  @InjectMocks private UserSettingsService service;

  private UUID userId;
  private User user;

  @BeforeEach
  void setUp() {
    userId = UUID.randomUUID();
    user = new User();
    user.setId(userId);
    user.setEmail("settings@otterworks.dev");
    user.setDisplayName("Settings User");
  }

  private UserSettings existingSettings() {
    UserSettings settings = new UserSettings();
    settings.setUser(user);
    settings.setNotificationEmail(false);
    settings.setNotificationInApp(true);
    settings.setNotificationDesktop(false);
    settings.setTheme("dark");
    settings.setLanguage("fr");
    return settings;
  }

  @Test
  void getSettings_returnsStoredSettings() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(existingSettings()));

    UserSettingsDTO dto = service.getSettings(userId);

    assertThat(dto.isNotificationEmail()).isFalse();
    assertThat(dto.isNotificationInApp()).isTrue();
    assertThat(dto.isNotificationDesktop()).isFalse();
    assertThat(dto.getTheme()).isEqualTo("dark");
    assertThat(dto.getLanguage()).isEqualTo("fr");
    verify(settingsRepository, never()).save(any());
  }

  @Test
  void getSettings_createsDefaultsWhenMissing() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UserSettingsDTO dto = service.getSettings(userId);

    ArgumentCaptor<UserSettings> saved = ArgumentCaptor.forClass(UserSettings.class);
    verify(settingsRepository).save(saved.capture());
    assertThat(saved.getValue().getUser()).isSameAs(user);
    assertThat(dto.isNotificationEmail()).isTrue();
    assertThat(dto.isNotificationInApp()).isTrue();
    assertThat(dto.isNotificationDesktop()).isFalse();
    assertThat(dto.getTheme()).isEqualTo("system");
    assertThat(dto.getLanguage()).isEqualTo("en");
  }

  @Test
  void getSettings_rejectsUnknownUser() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> service.getSettings(userId))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(settingsRepository, never()).save(any());
  }

  @Test
  void updateSettings_appliesEveryProvidedField() {
    UserSettings settings = existingSettings();
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(settings));
    when(settingsRepository.save(settings)).thenReturn(settings);

    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setNotificationEmail(true);
    request.setNotificationInApp(false);
    request.setNotificationDesktop(true);
    request.setTheme("light");
    request.setLanguage("de");

    UserSettingsDTO dto = service.updateSettings(userId, request);

    assertThat(settings.isNotificationEmail()).isTrue();
    assertThat(settings.isNotificationInApp()).isFalse();
    assertThat(settings.isNotificationDesktop()).isTrue();
    assertThat(settings.getTheme()).isEqualTo("light");
    assertThat(settings.getLanguage()).isEqualTo("de");
    assertThat(dto).isEqualTo(new UserSettingsDTO(true, false, true, "light", "de"));
  }

  @Test
  void updateSettings_ignoresNullFields() {
    UserSettings settings = existingSettings();
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(settings));
    when(settingsRepository.save(settings)).thenReturn(settings);

    UserSettingsDTO dto = service.updateSettings(userId, new UpdateSettingsRequest());

    assertThat(dto).isEqualTo(new UserSettingsDTO(false, true, false, "dark", "fr"));
  }

  @Test
  void updateSettings_appliesThemeOnlyToFreshDefaults() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setTheme("dark");

    UserSettingsDTO dto = service.updateSettings(userId, request);

    assertThat(dto.getTheme()).isEqualTo("dark");
    assertThat(dto.getLanguage()).isEqualTo("en");
  }
}
