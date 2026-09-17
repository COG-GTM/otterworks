package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.otterworks.auth.dto.AuthResponse;
import com.otterworks.auth.dto.ChangePasswordRequest;
import com.otterworks.auth.dto.LoginRequest;
import com.otterworks.auth.dto.RegisterRequest;
import com.otterworks.auth.dto.UpdateProfileRequest;
import com.otterworks.auth.dto.UserDTO;
import com.otterworks.auth.dto.UserLookupResponse;
import com.otterworks.auth.service.AuthService;
import com.otterworks.auth.service.UserService;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;

@ExtendWith(MockitoExtension.class)
class AuthControllerTest {

  @Mock private AuthService authService;
  @Mock private UserService userService;
  @Mock private Authentication authentication;

  @InjectMocks private AuthController authController;

  private UUID userId;
  private UserDTO userDto;

  @BeforeEach
  void setUp() {
    userId = UUID.randomUUID();
    userDto = new UserDTO();
    userDto.setId(userId.toString());
    userDto.setEmail("controller@otterworks.dev");
    userDto.setDisplayName("Controller User");
    userDto.setRoles(Set.of("USER"));
  }

  @Test
  void register_shouldReturn201() {
    RegisterRequest request = new RegisterRequest();
    AuthResponse authResponse = authResponse();
    when(authService.register(request)).thenReturn(authResponse);

    ResponseEntity<AuthResponse> response = authController.register(request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CREATED);
    assertThat(response.getBody()).isSameAs(authResponse);
  }

  @Test
  void login_shouldReturn200() {
    LoginRequest request = new LoginRequest();
    AuthResponse authResponse = authResponse();
    when(authService.login(request)).thenReturn(authResponse);

    ResponseEntity<AuthResponse> response = authController.login(request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody()).isSameAs(authResponse);
  }

  @Test
  void refresh_shouldStripBearerPrefix() {
    AuthResponse authResponse = authResponse();
    when(authService.refreshToken("raw-refresh-token")).thenReturn(authResponse);

    ResponseEntity<AuthResponse> response = authController.refresh("Bearer raw-refresh-token");

    assertThat(response.getBody()).isSameAs(authResponse);
  }

  @Test
  void refresh_shouldAcceptTokenWithoutBearerPrefix() {
    AuthResponse authResponse = authResponse();
    when(authService.refreshToken("raw-refresh-token")).thenReturn(authResponse);

    ResponseEntity<AuthResponse> response = authController.refresh("raw-refresh-token");

    assertThat(response.getBody()).isSameAs(authResponse);
  }

  @Test
  void getProfile_shouldResolvePrincipalAsUserId() {
    when(authentication.getPrincipal()).thenReturn(userId.toString());
    when(userService.getProfile(userId)).thenReturn(userDto);

    ResponseEntity<UserDTO> response = authController.getProfile(authentication);

    assertThat(response.getBody()).isSameAs(userDto);
  }

  @Test
  void updateProfile_shouldDelegateToUserService() {
    UpdateProfileRequest request = new UpdateProfileRequest();
    when(authentication.getPrincipal()).thenReturn(userId.toString());
    when(userService.updateProfile(userId, request)).thenReturn(userDto);

    ResponseEntity<UserDTO> response = authController.updateProfile(authentication, request);

    assertThat(response.getBody()).isSameAs(userDto);
  }

  @Test
  void changePassword_shouldReturn204() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    when(authentication.getPrincipal()).thenReturn(userId.toString());

    ResponseEntity<Void> response = authController.changePassword(authentication, request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);
    verify(authService).changePassword(userId, request);
  }

  @Test
  void lookupUser_shouldProjectOntoLookupResponse() {
    when(userService.findByEmail("controller@otterworks.dev")).thenReturn(userDto);

    ResponseEntity<UserLookupResponse> response =
        authController.lookupUser("controller@otterworks.dev");

    UserLookupResponse body = response.getBody();
    assertThat(body).isNotNull();
    assertThat(body.getId()).isEqualTo(userId.toString());
    assertThat(body.getEmail()).isEqualTo("controller@otterworks.dev");
    assertThat(body.getDisplayName()).isEqualTo("Controller User");
  }

  @Test
  void lookupUserById_shouldProjectOntoLookupResponse() {
    when(userService.getProfile(userId)).thenReturn(userDto);

    ResponseEntity<UserLookupResponse> response = authController.lookupUserById(userId);

    assertThat(response.getBody()).isNotNull();
    assertThat(response.getBody().getId()).isEqualTo(userId.toString());
  }

  @Test
  void listUsers_shouldReturnPage() {
    Pageable pageable = PageRequest.of(0, 20);
    Page<UserDTO> page = new PageImpl<>(List.of(userDto), pageable, 1);
    when(userService.listUsers(pageable)).thenReturn(page);

    ResponseEntity<Page<UserDTO>> response = authController.listUsers(pageable);

    assertThat(response.getBody()).isSameAs(page);
  }

  @Test
  void logout_shouldReturn204AndRevokeTokens() {
    when(authentication.getPrincipal()).thenReturn(userId.toString());

    ResponseEntity<Void> response = authController.logout(authentication);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);
    verify(authService).logout(userId);
  }

  private AuthResponse authResponse() {
    return new AuthResponse(
        "access-token",
        "refresh-token",
        "Bearer",
        3600L,
        new AuthResponse.UserDto(
            userId.toString(), "controller@otterworks.dev", "Controller User", null));
  }
}
