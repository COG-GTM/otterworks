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
  }

  @Test
  void getSettings_shouldReturnExistingSettings() {
    UserSettings existing = new UserSettings();
    existing.setTheme("dark");
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(existing));

    UserSettingsDTO dto = service.getSettings(userId);

    assertThat(dto.getTheme()).isEqualTo("dark");
    verify(settingsRepository, never()).save(any());
  }

  @Test
  void getSettings_shouldCreateDefaultsWhenMissing() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UserSettingsDTO dto = service.getSettings(userId);

    assertThat(dto).isEqualTo(new UserSettingsDTO(true, true, false, "system", "en"));
    ArgumentCaptor<UserSettings> captor = ArgumentCaptor.forClass(UserSettings.class);
    verify(settingsRepository).save(captor.capture());
    assertThat(captor.getValue().getUser()).isSameAs(user);
  }

  @Test
  void getSettings_shouldThrowWhenUserMissing() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> service.getSettings(userId))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
  }

  @Test
  void updateSettings_shouldApplyAllProvidedFields() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(new UserSettings()));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));
    UpdateSettingsRequest req = new UpdateSettingsRequest();
    req.setNotificationEmail(false);
    req.setNotificationInApp(false);
    req.setNotificationDesktop(true);
    req.setTheme("dark");
    req.setLanguage("fr");

    UserSettingsDTO dto = service.updateSettings(userId, req);

    assertThat(dto).isEqualTo(new UserSettingsDTO(false, false, true, "dark", "fr"));
  }

  @Test
  void updateSettings_shouldKeepValuesForNullFields() {
    UserSettings existing = new UserSettings();
    existing.setTheme("light");
    existing.setLanguage("de");
    existing.setNotificationDesktop(true);
    when(settingsRepository.findById(userId)).thenReturn(Optional.of(existing));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));

    UserSettingsDTO dto = service.updateSettings(userId, new UpdateSettingsRequest());

    assertThat(dto).isEqualTo(new UserSettingsDTO(true, true, true, "light", "de"));
  }

  @Test
  void updateSettings_shouldCreateDefaultsBeforeApplyingWhenMissing() {
    when(settingsRepository.findById(userId)).thenReturn(Optional.empty());
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(settingsRepository.save(any(UserSettings.class))).thenAnswer(inv -> inv.getArgument(0));
    UpdateSettingsRequest req = new UpdateSettingsRequest();
    req.setTheme("dark");

    UserSettingsDTO dto = service.updateSettings(userId, req);

    assertThat(dto).isEqualTo(new UserSettingsDTO(true, true, false, "dark", "en"));
    verify(settingsRepository, times(2)).save(any(UserSettings.class));
  }
}
