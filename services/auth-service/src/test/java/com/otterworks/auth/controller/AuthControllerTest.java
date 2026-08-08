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
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;

@ExtendWith(MockitoExtension.class)
class AuthControllerTest {

  @Mock private AuthService authService;
  @Mock private UserService userService;

  @InjectMocks private AuthController controller;

  private UUID userId;
  private Authentication authentication;
  private UserDTO userDto;

  @BeforeEach
  void setUp() {
    userId = UUID.fromString("12345678-1234-1234-1234-123456789012");
    authentication = new UsernamePasswordAuthenticationToken(userId.toString(), null, List.of());
    userDto = new UserDTO();
    userDto.setId(userId.toString());
    userDto.setEmail("controller@otterworks.dev");
    userDto.setDisplayName("Controller User");
    userDto.setRoles(Set.of("USER"));
  }

  @Test
  void register_shouldReturn201WithTokens() {
    RegisterRequest request = new RegisterRequest();
    request.setEmail("controller@otterworks.dev");
    AuthResponse expected = authResponse();
    when(authService.register(request)).thenReturn(expected);

    ResponseEntity<AuthResponse> response = controller.register(request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CREATED);
    assertThat(response.getBody()).isSameAs(expected);
  }

  @Test
  void login_shouldReturn200WithTokens() {
    LoginRequest request = new LoginRequest();
    request.setEmail("controller@otterworks.dev");
    AuthResponse expected = authResponse();
    when(authService.login(request)).thenReturn(expected);

    ResponseEntity<AuthResponse> response = controller.login(request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody()).isSameAs(expected);
  }

  @Test
  void refresh_shouldStripTheBearerPrefixBeforeDelegating() {
    AuthResponse expected = authResponse();
    when(authService.refreshToken("raw-token")).thenReturn(expected);

    ResponseEntity<AuthResponse> response = controller.refresh("Bearer raw-token");

    assertThat(response.getBody()).isSameAs(expected);
  }

  @Test
  void refresh_shouldAcceptATokenSentWithoutThePrefix() {
    AuthResponse expected = authResponse();
    when(authService.refreshToken("raw-token")).thenReturn(expected);

    ResponseEntity<AuthResponse> response = controller.refresh("raw-token");

    assertThat(response.getBody()).isSameAs(expected);
  }

  @Test
  void getProfile_shouldResolveUserIdFromPrincipal() {
    when(userService.getProfile(userId)).thenReturn(userDto);

    ResponseEntity<UserDTO> response = controller.getProfile(authentication);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody()).isSameAs(userDto);
  }

  @Test
  void updateProfile_shouldDelegateToUserService() {
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("Renamed");
    when(userService.updateProfile(userId, request)).thenReturn(userDto);

    ResponseEntity<UserDTO> response = controller.updateProfile(authentication, request);

    assertThat(response.getBody()).isSameAs(userDto);
  }

  @Test
  void changePassword_shouldReturn204() {
    ChangePasswordRequest request = new ChangePasswordRequest();
    request.setCurrentPassword("old");
    request.setNewPassword("newpassword");

    ResponseEntity<Void> response = controller.changePassword(authentication, request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);
    verify(authService).changePassword(userId, request);
  }

  @Test
  void lookupUser_shouldReturnTheReducedProjection() {
    when(userService.findByEmail("controller@otterworks.dev")).thenReturn(userDto);

    ResponseEntity<UserLookupResponse> response =
        controller.lookupUser("controller@otterworks.dev");

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody())
        .isEqualTo(
            new UserLookupResponse(
                userId.toString(), "controller@otterworks.dev", "Controller User"));
  }

  @Test
  void lookupUserById_shouldReturnTheReducedProjection() {
    when(userService.getProfile(userId)).thenReturn(userDto);

    ResponseEntity<UserLookupResponse> response = controller.lookupUserById(userId);

    assertThat(response.getBody().getId()).isEqualTo(userId.toString());
    assertThat(response.getBody().getEmail()).isEqualTo("controller@otterworks.dev");
    assertThat(response.getBody().getDisplayName()).isEqualTo("Controller User");
  }

  @Test
  void listUsers_shouldPassThePageableThrough() {
    Pageable pageable = PageRequest.of(1, 5);
    Page<UserDTO> page = new PageImpl<>(List.of(userDto), pageable, 6);
    when(userService.listUsers(pageable)).thenReturn(page);

    ResponseEntity<Page<UserDTO>> response = controller.listUsers(pageable);

    assertThat(response.getBody()).isSameAs(page);
  }

  @Test
  void logout_shouldReturn204AndRevokeTokens() {
    ResponseEntity<Void> response = controller.logout(authentication);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);
    verify(authService).logout(userId);
  }

  private AuthResponse authResponse() {
    return new AuthResponse(
        "access",
        "refresh",
        "Bearer",
        3600,
        new AuthResponse.UserDto(
            userId.toString(), "controller@otterworks.dev", "Controller User", null));
  }
}
