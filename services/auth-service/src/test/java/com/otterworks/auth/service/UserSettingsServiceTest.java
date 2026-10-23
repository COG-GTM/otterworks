package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

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
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class UserSettingsServiceTest {

  @Mock private UserSettingsRepository settingsRepository;
  @Mock private UserRepository userRepository;

  @InjectMocks private UserSettingsService settingsService;

  private UUID userId;
  private User user;

  @BeforeEach
  void setUp() {
    userId = UUID.randomUUID();
    user = new User();
    user.setId(userId);
  }

  @Test
  void getSettings_createsDefaultsOnFirstRead() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UserSettingsDTO dto = settingsService.getSettings(userId);

    assertThat(dto.isNotificationEmail()).isTrue();
    assertThat(dto.isNotificationInApp()).isTrue();
    assertThat(dto.isNotificationDesktop()).isFalse();
    assertThat(dto.getTheme()).isEqualTo("system");
    assertThat(dto.getLanguage()).isEqualTo("en");
    verify(settingsRepository).save(any(UserSettings.class));
  }

  @Test
  void getSettings_returnsExistingWithoutSaving() {
    UserSettings existing = new UserSettings();
    existing.setTheme("dark");
    existing.setNotificationEmail(false);
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(existing));

    UserSettingsDTO dto = settingsService.getSettings(userId);

    assertThat(dto.getTheme()).isEqualTo("dark");
    assertThat(dto.isNotificationEmail()).isFalse();
    verify(settingsRepository, never()).save(any());
    verifyNoInteractions(userRepository);
  }

  @Test
  void getSettings_unknownUserThrows() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> settingsService.getSettings(userId))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
  }

  @Test
  void updateSettings_appliesOnlyNonNullFields() {
    UserSettings existing = new UserSettings();
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(existing));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));
    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setNotificationDesktop(true);
    request.setTheme("dark");

    UserSettingsDTO dto = settingsService.updateSettings(userId, request);

    assertThat(dto.isNotificationDesktop()).isTrue();
    assertThat(dto.getTheme()).isEqualTo("dark");
    assertThat(dto.isNotificationEmail()).isTrue();
    assertThat(dto.isNotificationInApp()).isTrue();
    assertThat(dto.getLanguage()).isEqualTo("en");
  }

  @Test
  void updateSettings_allFields() {
    UserSettings existing = new UserSettings();
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(existing));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));
    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setNotificationEmail(false);
    request.setNotificationInApp(false);
    request.setNotificationDesktop(true);
    request.setTheme("light");
    request.setLanguage("fr");

    UserSettingsDTO dto = settingsService.updateSettings(userId, request);

    assertThat(dto)
        .extracting(
            UserSettingsDTO::isNotificationEmail,
            UserSettingsDTO::isNotificationInApp,
            UserSettingsDTO::isNotificationDesktop,
            UserSettingsDTO::getTheme,
            UserSettingsDTO::getLanguage)
        .containsExactly(false, false, true, "light", "fr");
  }

  @Test
  void updateSettings_createsDefaultsWhenMissing() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));
    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setLanguage("de");

    UserSettingsDTO dto = settingsService.updateSettings(userId, request);

    assertThat(dto.getLanguage()).isEqualTo("de");
    verify(settingsRepository, times(2)).save(any(UserSettings.class));
  }
}
