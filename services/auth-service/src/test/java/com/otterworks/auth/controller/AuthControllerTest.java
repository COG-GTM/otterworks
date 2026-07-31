package com.otterworks.auth.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
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
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
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

  @BeforeEach
  void setUp() {
    userId = UUID.randomUUID();
    authentication = new UsernamePasswordAuthenticationToken(userId.toString(), null, List.of());
  }

  private static AuthResponse authResponse() {
    return new AuthResponse(
        "access",
        "refresh",
        "Bearer",
        3600L,
        new AuthResponse.UserDto("id-1", "user@otterworks.dev", "User One", null));
  }

  private UserDTO userDto() {
    UserDTO dto = new UserDTO();
    dto.setId(userId.toString());
    dto.setEmail("user@otterworks.dev");
    dto.setDisplayName("User One");
    return dto;
  }

  @Test
  void register_returns201WithTheIssuedTokens() {
    RegisterRequest request = new RegisterRequest();
    when(authService.register(request)).thenReturn(authResponse());

    ResponseEntity<AuthResponse> response = controller.register(request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CREATED);
    assertThat(response.getBody()).isEqualTo(authResponse());
  }

  @Test
  void login_returns200WithTheIssuedTokens() {
    LoginRequest request = new LoginRequest();
    when(authService.login(request)).thenReturn(authResponse());

    ResponseEntity<AuthResponse> response = controller.login(request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody()).isEqualTo(authResponse());
  }

  @ParameterizedTest(name = "Authorization header \"{0}\" yields the bare token")
  @ValueSource(strings = {"Bearer refresh-token", "refresh-token"})
  void refresh_stripsTheBearerPrefixBeforeDelegating(String header) {
    when(authService.refreshToken("refresh-token")).thenReturn(authResponse());

    ResponseEntity<AuthResponse> response = controller.refresh(header);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    verify(authService).refreshToken("refresh-token");
  }

  @Test
  void getProfile_resolvesTheUserIdFromThePrincipal() {
    when(userService.getProfile(userId)).thenReturn(userDto());

    ResponseEntity<UserDTO> response = controller.getProfile(authentication);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody().getEmail()).isEqualTo("user@otterworks.dev");
  }

  @Test
  void updateProfile_delegatesToTheAuthenticatedUsersOwnProfile() {
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("Renamed");
    when(userService.updateProfile(userId, request)).thenReturn(userDto());

    ResponseEntity<UserDTO> response = controller.updateProfile(authentication, request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    verify(userService).updateProfile(userId, request);
  }

  @Test
  void changePassword_returns204AndDelegatesToTheAuthenticatedUser() {
    ChangePasswordRequest request = new ChangePasswordRequest();

    ResponseEntity<Void> response = controller.changePassword(authentication, request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);
    assertThat(response.getBody()).isNull();
    verify(authService).changePassword(userId, request);
  }

  @Test
  void lookupUser_returnsOnlyTheIdentityFieldsForAnEmail() {
    when(userService.findByEmail("user@otterworks.dev")).thenReturn(userDto());

    ResponseEntity<UserLookupResponse> response = controller.lookupUser("user@otterworks.dev");

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody())
        .isEqualTo(new UserLookupResponse(userId.toString(), "user@otterworks.dev", "User One"));
  }

  @Test
  void lookupUserById_returnsOnlyTheIdentityFields() {
    when(userService.getProfile(userId)).thenReturn(userDto());

    ResponseEntity<UserLookupResponse> response = controller.lookupUserById(userId);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody().getDisplayName()).isEqualTo("User One");
  }

  @Test
  void listUsers_passesThePageableStraightThrough() {
    Pageable pageable = PageRequest.of(2, 5);
    Page<UserDTO> page = new PageImpl<>(List.of(userDto()), pageable, 11);
    when(userService.listUsers(pageable)).thenReturn(page);

    ResponseEntity<Page<UserDTO>> response = controller.listUsers(pageable);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody().getTotalElements()).isEqualTo(11);
    verifyNoInteractions(authService);
  }

  @Test
  void logout_returns204AndRevokesTheAuthenticatedUsersTokens() {
    ResponseEntity<Void> response = controller.logout(authentication);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);
    verify(authService).logout(userId);
  }
}
