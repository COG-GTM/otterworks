package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
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
    user.setEmail("user@otterworks.dev");
    user.setDisplayName("User One");
  }

  private static UserSettings storedSettings() {
    UserSettings settings = new UserSettings();
    settings.setNotificationEmail(false);
    settings.setNotificationInApp(true);
    settings.setNotificationDesktop(true);
    settings.setTheme("dark");
    settings.setLanguage("fr");
    return settings;
  }

  @Test
  void getSettings_returnsThePersistedSettingsWithoutWriting() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(storedSettings()));

    UserSettingsDTO dto = service.getSettings(userId);

    assertThat(dto).isEqualTo(new UserSettingsDTO(false, true, true, "dark", "fr"));
    verify(settingsRepository, never()).save(any());
    verifyNoInteractions(userRepository);
  }

  @Test
  void getSettings_createsAndPersistsDefaultsWhenNoRowExists() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(i -> i.getArgument(0));

    UserSettingsDTO dto = service.getSettings(userId);

    assertThat(dto).isEqualTo(new UserSettingsDTO(true, true, false, "system", "en"));
    ArgumentCaptor<UserSettings> saved = ArgumentCaptor.forClass(UserSettings.class);
    verify(settingsRepository).save(saved.capture());
    assertThat(saved.getValue().getUser()).isSameAs(user);
  }

  @Test
  void getSettings_rejectsAnUnknownUser() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> service.getSettings(userId))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(settingsRepository, never()).save(any());
  }

  @Test
  void updateSettings_appliesEveryProvidedField() {
    UserSettings settings = storedSettings();
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(settings));
    when(settingsRepository.save(settings)).thenReturn(settings);

    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setNotificationEmail(true);
    request.setNotificationInApp(false);
    request.setNotificationDesktop(false);
    request.setTheme("light");
    request.setLanguage("de");

    UserSettingsDTO dto = service.updateSettings(userId, request);

    assertThat(dto).isEqualTo(new UserSettingsDTO(true, false, false, "light", "de"));
    assertThat(settings.isNotificationEmail()).isTrue();
    assertThat(settings.getTheme()).isEqualTo("light");
    verify(settingsRepository).save(settings);
  }

  @Test
  void updateSettings_leavesOmittedFieldsUntouched() {
    UserSettings settings = storedSettings();
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(settings));
    when(settingsRepository.save(settings)).thenReturn(settings);

    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setTheme("light");

    UserSettingsDTO dto = service.updateSettings(userId, request);

    assertThat(dto).isEqualTo(new UserSettingsDTO(false, true, true, "light", "fr"));
  }

  @Test
  void updateSettings_withAnEmptyRequestIsANoOpThatStillPersists() {
    UserSettings settings = storedSettings();
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(settings));
    when(settingsRepository.save(settings)).thenReturn(settings);

    UserSettingsDTO dto = service.updateSettings(userId, new UpdateSettingsRequest());

    assertThat(dto).isEqualTo(new UserSettingsDTO(false, true, true, "dark", "fr"));
    verify(settingsRepository).save(settings);
  }

  @Test
  void updateSettings_createsDefaultsFirstWhenNoRowExists() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(i -> i.getArgument(0));

    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setNotificationDesktop(true);
    request.setLanguage("es");

    UserSettingsDTO dto = service.updateSettings(userId, request);

    assertThat(dto).isEqualTo(new UserSettingsDTO(true, true, true, "system", "es"));
    verify(settingsRepository, org.mockito.Mockito.times(2)).save(any(UserSettings.class));
  }

  @Test
  void updateSettings_rejectsAnUnknownUser() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> service.updateSettings(userId, new UpdateSettingsRequest()))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(settingsRepository, never()).save(any());
  }
}
