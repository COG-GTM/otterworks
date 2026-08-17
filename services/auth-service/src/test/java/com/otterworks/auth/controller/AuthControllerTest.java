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
    userId = UUID.randomUUID();
    authentication = new UsernamePasswordAuthenticationToken(userId.toString(), null, List.of());
    userDto = new UserDTO();
    userDto.setId(userId.toString());
    userDto.setEmail("api@otterworks.dev");
    userDto.setDisplayName("Api User");
    userDto.setRoles(Set.of("USER"));
  }

  private AuthResponse authResponse() {
    return new AuthResponse(
        "access",
        "refresh",
        "Bearer",
        3600L,
        new AuthResponse.UserDto(userId.toString(), "api@otterworks.dev", "Api User", null));
  }

  @Test
  void register_returns201WithTokens() {
    RegisterRequest request = new RegisterRequest();
    when(authService.register(request)).thenReturn(authResponse());

    ResponseEntity<AuthResponse> response = controller.register(request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CREATED);
    assertThat(response.getBody().getAccessToken()).isEqualTo("access");
  }

  @Test
  void login_returns200WithTokens() {
    LoginRequest request = new LoginRequest();
    when(authService.login(request)).thenReturn(authResponse());

    ResponseEntity<AuthResponse> response = controller.login(request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    assertThat(response.getBody().getRefreshToken()).isEqualTo("refresh");
  }

  @Test
  void refresh_stripsTheBearerPrefixBeforeDelegating() {
    when(authService.refreshToken("raw-token")).thenReturn(authResponse());

    ResponseEntity<AuthResponse> response = controller.refresh("Bearer raw-token");

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    verify(authService).refreshToken("raw-token");
  }

  @Test
  void getProfile_resolvesTheUserFromThePrincipal() {
    when(userService.getProfile(userId)).thenReturn(userDto);

    ResponseEntity<UserDTO> response = controller.getProfile(authentication);

    assertThat(response.getBody().getEmail()).isEqualTo("api@otterworks.dev");
  }

  @Test
  void updateProfile_delegatesToTheService() {
    UpdateProfileRequest request = new UpdateProfileRequest();
    when(userService.updateProfile(userId, request)).thenReturn(userDto);

    ResponseEntity<UserDTO> response = controller.updateProfile(authentication, request);

    assertThat(response.getBody()).isSameAs(userDto);
  }

  @Test
  void changePassword_returns204() {
    ChangePasswordRequest request = new ChangePasswordRequest();

    ResponseEntity<Void> response = controller.changePassword(authentication, request);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);
    verify(authService).changePassword(userId, request);
  }

  @Test
  void lookupUser_returnsOnlyThePublicFields() {
    when(userService.findByEmail("api@otterworks.dev")).thenReturn(userDto);

    ResponseEntity<UserLookupResponse> response = controller.lookupUser("api@otterworks.dev");

    assertThat(response.getBody())
        .isEqualTo(new UserLookupResponse(userId.toString(), "api@otterworks.dev", "Api User"));
  }

  @Test
  void lookupUserById_returnsOnlyThePublicFields() {
    when(userService.getProfile(userId)).thenReturn(userDto);

    ResponseEntity<UserLookupResponse> response = controller.lookupUserById(userId);

    assertThat(response.getBody().getId()).isEqualTo(userId.toString());
    assertThat(response.getBody().getDisplayName()).isEqualTo("Api User");
  }

  @Test
  void listUsers_passesThePageableThrough() {
    Pageable pageable = PageRequest.of(1, 5);
    Page<UserDTO> page = new PageImpl<>(List.of(userDto), pageable, 6);
    when(userService.listUsers(pageable)).thenReturn(page);

    ResponseEntity<Page<UserDTO>> response = controller.listUsers(pageable);

    assertThat(response.getBody().getTotalElements()).isEqualTo(6);
  }

  @Test
  void logout_returns204AndRevokesTokens() {
    ResponseEntity<Void> response = controller.logout(authentication);

    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NO_CONTENT);
    verify(authService).logout(userId);
  }
}
