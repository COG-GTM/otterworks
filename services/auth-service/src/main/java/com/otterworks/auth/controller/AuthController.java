package com.otterworks.auth.controller;

import com.otterworks.auth.dto.*;
import com.otterworks.auth.service.AuthService;
import com.otterworks.auth.service.UserService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
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

  public AuthController(AuthService authService, UserService userService) {
    this.authService = authService;
    this.userService = userService;
  }

  @PostMapping("/register")
  public ResponseEntity<AuthResponse> register(@Valid @RequestBody RegisterRequest request) {
    AuthResponse response = authService.register(request);
    return ResponseEntity.status(HttpStatus.CREATED).body(response);
  }

  @PostMapping("/login")
  public ResponseEntity<AuthResponse> login(@Valid @RequestBody LoginRequest request) {
    AuthResponse response = authService.login(request);
    return ResponseEntity.ok(response);
  }

  @PostMapping("/refresh")
  public ResponseEntity<AuthResponse> refresh(@RequestHeader("Authorization") String bearerToken) {
    String token = bearerToken.replace("Bearer ", "");
    AuthResponse response = authService.refreshToken(token);
    return ResponseEntity.ok(response);
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

  @PatchMapping("/users/{id}/quota")
  @PreAuthorize("hasRole('ADMIN')")
  public ResponseEntity<UserDTO> updateQuota(
      @PathVariable UUID id, @Valid @RequestBody UpdateQuotaRequest request) {
    UserDTO user = userService.updateQuota(id, request.getQuotaBytes());
    return ResponseEntity.ok(user);
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
    return ResponseEntity.noContent().build();
  }
}
