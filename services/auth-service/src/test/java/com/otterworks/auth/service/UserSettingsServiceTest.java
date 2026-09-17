package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
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

  @InjectMocks private UserSettingsService userSettingsService;

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

  @Test
  void getSettings_shouldReturnExistingSettings() {
    UserSettings settings = new UserSettings();
    settings.setUser(user);
    settings.setNotificationEmail(false);
    settings.setNotificationInApp(true);
    settings.setNotificationDesktop(true);
    settings.setTheme("dark");
    settings.setLanguage("fr");
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(settings));

    UserSettingsDTO dto = userSettingsService.getSettings(userId);

    assertThat(dto.isNotificationEmail()).isFalse();
    assertThat(dto.isNotificationInApp()).isTrue();
    assertThat(dto.isNotificationDesktop()).isTrue();
    assertThat(dto.getTheme()).isEqualTo("dark");
    assertThat(dto.getLanguage()).isEqualTo("fr");
    verify(settingsRepository, never()).save(any());
  }

  @Test
  void getSettings_shouldCreateDefaultsWhenAbsent() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UserSettingsDTO dto = userSettingsService.getSettings(userId);

    assertThat(dto.isNotificationEmail()).isTrue();
    assertThat(dto.isNotificationInApp()).isTrue();
    assertThat(dto.isNotificationDesktop()).isFalse();
    assertThat(dto.getTheme()).isEqualTo("system");
    assertThat(dto.getLanguage()).isEqualTo("en");

    ArgumentCaptor<UserSettings> captor = ArgumentCaptor.forClass(UserSettings.class);
    verify(settingsRepository).save(captor.capture());
    assertThat(captor.getValue().getUser()).isSameAs(user);
  }

  @Test
  void getSettings_shouldRejectUnknownUser() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userSettingsService.getSettings(userId))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(settingsRepository, never()).save(any());
  }

  @Test
  void updateSettings_shouldApplyEveryProvidedField() {
    UserSettings settings = new UserSettings();
    settings.setUser(user);
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(settings));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setNotificationEmail(false);
    request.setNotificationInApp(false);
    request.setNotificationDesktop(true);
    request.setTheme("light");
    request.setLanguage("de");

    UserSettingsDTO dto = userSettingsService.updateSettings(userId, request);

    assertThat(dto.isNotificationEmail()).isFalse();
    assertThat(dto.isNotificationInApp()).isFalse();
    assertThat(dto.isNotificationDesktop()).isTrue();
    assertThat(dto.getTheme()).isEqualTo("light");
    assertThat(dto.getLanguage()).isEqualTo("de");
  }

  @Test
  void updateSettings_shouldLeaveOmittedFieldsUntouched() {
    UserSettings settings = new UserSettings();
    settings.setUser(user);
    settings.setTheme("dark");
    settings.setLanguage("fr");
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(settings));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UserSettingsDTO dto = userSettingsService.updateSettings(userId, new UpdateSettingsRequest());

    assertThat(dto.isNotificationEmail()).isTrue();
    assertThat(dto.isNotificationInApp()).isTrue();
    assertThat(dto.isNotificationDesktop()).isFalse();
    assertThat(dto.getTheme()).isEqualTo("dark");
    assertThat(dto.getLanguage()).isEqualTo("fr");
  }

  @Test
  void updateSettings_shouldCreateDefaultsWhenAbsent() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setTheme("light");

    UserSettingsDTO dto = userSettingsService.updateSettings(userId, request);

    assertThat(dto.getTheme()).isEqualTo("light");
    verify(settingsRepository, times(2)).save(any(UserSettings.class));
  }
}
