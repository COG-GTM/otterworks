package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.otterworks.auth.dto.UpdateSettingsRequest;
import com.otterworks.auth.dto.UserSettingsDTO;
import com.otterworks.auth.service.UserSettingsService;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;

@ExtendWith(MockitoExtension.class)
class SettingsControllerTest {

  @Mock private UserSettingsService settingsService;

  @InjectMocks private SettingsController controller;

  private UUID userId;
  private Authentication authentication;

  @BeforeEach
  void setUp() {
    userId = UUID.randomUUID();
    authentication = new UsernamePasswordAuthenticationToken(userId.toString(), null, List.of());
  }

  @Test
  void getSettings_returnsTheSettingsOfTheAuthenticatedUser() {
    UserSettingsDTO settings = new UserSettingsDTO(true, false, true, "dark", "fr");
    when(settingsService.getSettings(userId)).thenReturn(settings);

    ResponseEntity<UserSettingsDTO> response = controller.getSettings(authentication);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody()).isEqualTo(settings);
    verify(settingsService).getSettings(userId);
  }

  @Test
  void updateSettings_delegatesTheRequestForTheAuthenticatedUser() {
    UpdateSettingsRequest request = new UpdateSettingsRequest();
    request.setTheme("light");
    UserSettingsDTO updated = new UserSettingsDTO(true, true, false, "light", "en");
    when(settingsService.updateSettings(userId, request)).thenReturn(updated);

    ResponseEntity<UserSettingsDTO> response = controller.updateSettings(authentication, request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody()).isEqualTo(updated);
    verify(settingsService).updateSettings(userId, request);
  }

  @Test
  void aPrincipalThatIsNotAUuidIsRejectedRatherThanReadingAnotherUsersSettings() {
    Authentication bad = new UsernamePasswordAuthenticationToken("not-a-uuid", null, List.of());

    assertThatThrownBy(() -> controller.getSettings(bad))
        .isInstanceOf(IllegalArgumentException.class);
  }
}
