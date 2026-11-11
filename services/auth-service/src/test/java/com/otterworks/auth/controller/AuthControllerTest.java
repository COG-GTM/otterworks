package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;

import com.otterworks.auth.dto.RegisterRequest;
import com.otterworks.auth.service.AuthService;
import com.otterworks.auth.service.UserService;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.ResponseEntity;

class AuthControllerTest {

  private final AuthService authService = mock(AuthService.class);
  private final AuthController controller =
      new AuthController(authService, mock(UserService.class));

  @Test
  void register_losingConcurrentRegistrationRace_returnsSameResponseAsSuccess() {
    RegisterRequest request = new RegisterRequest();
    request.setEmail("race@otterworks.dev");
    request.setPassword("password123");
    request.setDisplayName("Race");

    doNothing().when(authService).register(any(RegisterRequest.class));
    ResponseEntity<Map<String, String>> won = controller.register(request);

    doThrow(new DataIntegrityViolationException("duplicate key value violates unique constraint"))
        .when(authService)
        .register(any(RegisterRequest.class));
    ResponseEntity<Map<String, String>> lost = controller.register(request);

    assertThat(lost.getStatusCode()).isEqualTo(won.getStatusCode());
    assertThat(lost.getStatusCode().value()).isEqualTo(202);
    assertThat(lost.getBody()).isEqualTo(won.getBody());
  }
}
