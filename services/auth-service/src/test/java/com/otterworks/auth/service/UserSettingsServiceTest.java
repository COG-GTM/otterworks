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
    userId = UUID.fromString("11111111-2222-3333-4444-555555555555");
    user = new User();
    user.setId(userId);
    user.setEmail("settings@otterworks.dev");
    user.setDisplayName("Settings User");
  }

  @Test
  void getSettings_shouldReturnExistingSettings() {
    UserSettings stored = new UserSettings();
    stored.setUser(user);
    stored.setNotificationEmail(false);
    stored.setNotificationInApp(false);
    stored.setNotificationDesktop(true);
    stored.setTheme("dark");
    stored.setLanguage("fr");
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(stored));

    UserSettingsDTO dto = service.getSettings(userId);

    assertThat(dto.isNotificationEmail()).isFalse();
    assertThat(dto.isNotificationInApp()).isFalse();
    assertThat(dto.isNotificationDesktop()).isTrue();
    assertThat(dto.getTheme()).isEqualTo("dark");
    assertThat(dto.getLanguage()).isEqualTo("fr");
    verify(settingsRepository, never()).save(any(UserSettings.class));
  }

  @Test
  void getSettings_shouldCreateDefaultsWhenNoneStored() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UserSettingsDTO dto = service.getSettings(userId);

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

    assertThatThrownBy(() -> service.getSettings(userId))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(settingsRepository, never()).save(any(UserSettings.class));
  }

  @Test
  void updateSettings_shouldApplyEveryProvidedField() {
    UserSettings stored = new UserSettings();
    stored.setUser(user);
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(stored));
    when(settingsRepository.save(stored)).thenReturn(stored);

    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setNotificationEmail(false);
    request.setNotificationInApp(false);
    request.setNotificationDesktop(true);
    request.setTheme("dark");
    request.setLanguage("de");

    UserSettingsDTO dto = service.updateSettings(userId, request);

    assertThat(stored.isNotificationEmail()).isFalse();
    assertThat(stored.isNotificationInApp()).isFalse();
    assertThat(stored.isNotificationDesktop()).isTrue();
    assertThat(stored.getTheme()).isEqualTo("dark");
    assertThat(stored.getLanguage()).isEqualTo("de");
    assertThat(dto).isEqualTo(UserSettingsDTO.fromEntity(stored));
  }

  @Test
  void updateSettings_shouldLeaveOmittedFieldsUntouched() {
    UserSettings stored = new UserSettings();
    stored.setUser(user);
    stored.setTheme("dark");
    stored.setLanguage("fr");
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(stored));
    when(settingsRepository.save(stored)).thenReturn(stored);

    UserSettingsDTO dto = service.updateSettings(userId, new UpdateSettingsRequest());

    assertThat(stored.isNotificationEmail()).isTrue();
    assertThat(stored.isNotificationInApp()).isTrue();
    assertThat(stored.isNotificationDesktop()).isFalse();
    assertThat(dto.getTheme()).isEqualTo("dark");
    assertThat(dto.getLanguage()).isEqualTo("fr");
  }

  @Test
  void updateSettings_shouldApplyThemeOnlyWithoutTouchingNotifications() {
    UserSettings stored = new UserSettings();
    stored.setUser(user);
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(stored));
    when(settingsRepository.save(stored)).thenReturn(stored);

    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setTheme("light");

    service.updateSettings(userId, request);

    assertThat(stored.getTheme()).isEqualTo("light");
    assertThat(stored.getLanguage()).isEqualTo("en");
    assertThat(stored.isNotificationEmail()).isTrue();
  }

  @Test
  void updateSettings_shouldCreateDefaultsFirstWhenNoneStored() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setLanguage("es");

    UserSettingsDTO dto = service.updateSettings(userId, request);

    assertThat(dto.getLanguage()).isEqualTo("es");
    verify(settingsRepository, org.mockito.Mockito.times(2)).save(any(UserSettings.class));
  }
}
