package com.otterworks.auth.service;

import com.otterworks.auth.dto.UpdateSettingsRequest;
import com.otterworks.auth.dto.UserSettingsDTO;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.entity.UserSettings;
import com.otterworks.auth.exception.BadRequestException;
import com.otterworks.auth.repository.UserRepository;
import com.otterworks.auth.repository.UserSettingsRepository;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class UserSettingsService {

  private static final Logger log = LoggerFactory.getLogger(UserSettingsService.class);

  private final UserSettingsRepository settingsRepository;
  private final UserRepository userRepository;

  public UserSettingsService(
      UserSettingsRepository settingsRepository, UserRepository userRepository) {
    this.settingsRepository = settingsRepository;
    this.userRepository = userRepository;
  }

  @Transactional
  public UserSettingsDTO getSettings(UUID userId) {
    UserSettings settings =
        settingsRepository.findById(userId).orElseGet(() -> createDefaultSettings(userId));
    return UserSettingsDTO.fromEntity(settings);
  }

  @Transactional
  public UserSettingsDTO updateSettings(UUID userId, UpdateSettingsRequest request) {
    UserSettings settings =
        settingsRepository.findById(userId).orElseGet(() -> createDefaultSettings(userId));

    if (request.getNotificationEmail() != null) {
      settings.setNotificationEmail(request.getNotificationEmail());
    }
    if (request.getNotificationInApp() != null) {
      settings.setNotificationInApp(request.getNotificationInApp());
    }
    if (request.getNotificationDesktop() != null) {
      settings.setNotificationDesktop(request.getNotificationDesktop());
    }
    if (request.getTheme() != null) {
      settings.setTheme(request.getTheme());
    }
    if (request.getLanguage() != null) {
      settings.setLanguage(request.getLanguage());
    }

    settings = settingsRepository.save(settings);
    log.info("Settings updated for user: {}", userId);
    return UserSettingsDTO.fromEntity(settings);
  }

  private UserSettings createDefaultSettings(UUID userId) {
    User user =
        userRepository
            .findById(userId)
            .orElseThrow(() -> new BadRequestException("User not found"));
    UserSettings settings = new UserSettings();
    settings.setUser(user);
    return settingsRepository.save(settings);
  }
}
