package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

import com.otterworks.auth.dto.UpdateSettingsRequest;
import com.otterworks.auth.dto.UserSettingsDTO;
import com.otterworks.auth.service.UserSettingsService;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;

@ExtendWith(MockitoExtension.class)
class SettingsControllerTest {

  @Mock private UserSettingsService settingsService;
  @Mock private Authentication authentication;

  @InjectMocks private SettingsController settingsController;

  private UUID userId;

  @BeforeEach
  void setUp() {
    userId = UUID.randomUUID();
    when(authentication.getPrincipal()).thenReturn(userId.toString());
  }

  @Test
  void getSettings_shouldReturnServiceResult() {
    UserSettingsDTO dto = new UserSettingsDTO(true, true, false, "system", "en");
    when(settingsService.getSettings(userId)).thenReturn(dto);

    ResponseEntity<UserSettingsDTO> response = settingsController.getSettings(authentication);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody()).isSameAs(dto);
  }

  @Test
  void updateSettings_shouldPassRequestThroughToService() {
    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setTheme("dark");
    UserSettingsDTO dto = new UserSettingsDTO(true, true, false, "dark", "en");
    when(settingsService.updateSettings(userId, request)).thenReturn(dto);

    ResponseEntity<UserSettingsDTO> response =
        settingsController.updateSettings(authentication, request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody()).isSameAs(dto);
  }
}
