package com.otterworks.auth.controller;

import com.otterworks.auth.dto.*;
import com.otterworks.auth.security.RefreshTokenCookie;
import com.otterworks.auth.service.AuthService;
import com.otterworks.auth.service.UserService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

  private final AuthService authService;
  private final UserService userService;
  private final RefreshTokenCookie refreshTokenCookie;

  public AuthController(
      AuthService authService, UserService userService, RefreshTokenCookie refreshTokenCookie) {
    this.authService = authService;
    this.userService = userService;
    this.refreshTokenCookie = refreshTokenCookie;
  }

  @PostMapping("/register")
  public ResponseEntity<AuthResponse> register(@Valid @RequestBody RegisterRequest request) {
    return withRefreshCookie(
        ResponseEntity.status(HttpStatus.CREATED), authService.register(request));
  }

  @PostMapping("/login")
  public ResponseEntity<AuthResponse> login(@Valid @RequestBody LoginRequest request) {
    return withRefreshCookie(ResponseEntity.ok(), authService.login(request));
  }

  @PostMapping("/refresh")
  public ResponseEntity<AuthResponse> refresh(HttpServletRequest request) {
    String token = refreshTokenCookie.read(request);
    if (token == null) {
      return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
          .header(HttpHeaders.SET_COOKIE, refreshTokenCookie.clear().toString())
          .build();
    }
    return withRefreshCookie(ResponseEntity.ok(), authService.refreshToken(token));
  }

  @GetMapping("/profile")
  public ResponseEntity<UserDTO> getProfile(Authentication authentication) {
    UUID userId = UUID.fromString((String) authentication.getPrincipal());
    UserDTO profile = userService.getProfile(userId);
    return ResponseEntity.ok(profile);
  }

  @PutMapping("/profile")
  public ResponseEntity<UserDTO> updateProfile(
      Authentication authentication, @Valid @RequestBody UpdateProfileRequest request) {
    UUID userId = UUID.fromString((String) authentication.getPrincipal());
    UserDTO profile = userService.updateProfile(userId, request);
    return ResponseEntity.ok(profile);
  }

  @PostMapping("/change-password")
  public ResponseEntity<Void> changePassword(
      Authentication authentication, @Valid @RequestBody ChangePasswordRequest request) {
    UUID userId = UUID.fromString((String) authentication.getPrincipal());
    authService.changePassword(userId, request);
    return ResponseEntity.noContent().build();
  }

  @GetMapping("/users/lookup")
  public ResponseEntity<UserLookupResponse> lookupUser(@RequestParam String email) {
    UserDTO user = userService.findByEmail(email);
    return ResponseEntity.ok(UserLookupResponse.fromUserDTO(user));
  }

  @GetMapping("/users/by-id/{id}")
  public ResponseEntity<UserLookupResponse> lookupUserById(@PathVariable UUID id) {
    UserDTO user = userService.getProfile(id);
    return ResponseEntity.ok(UserLookupResponse.fromUserDTO(user));
  }

  @GetMapping("/users")
  @PreAuthorize("hasRole('ADMIN')")
  public ResponseEntity<Page<UserDTO>> listUsers(Pageable pageable) {
    Page<UserDTO> users = userService.listUsers(pageable);
    return ResponseEntity.ok(users);
  }

  @PostMapping("/logout")
  public ResponseEntity<Void> logout(Authentication authentication) {
    UUID userId = UUID.fromString((String) authentication.getPrincipal());
    authService.logout(userId);
    return ResponseEntity.noContent()
        .header(HttpHeaders.SET_COOKIE, refreshTokenCookie.clear().toString())
        .build();
  }

  private ResponseEntity<AuthResponse> withRefreshCookie(
      ResponseEntity.BodyBuilder builder, AuthResponse response) {
    String refreshToken = response.getRefreshToken();
    response.setRefreshToken(null);
    return builder
        .header(HttpHeaders.SET_COOKIE, refreshTokenCookie.issue(refreshToken).toString())
        .body(response);
  }
}
