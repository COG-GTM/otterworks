package com.otterworks.auth.controller;

import com.otterworks.auth.dto.*;
import com.otterworks.auth.service.AuthService;
import com.otterworks.auth.service.UserLookupRateLimiter;
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
  private final UserLookupRateLimiter lookupRateLimiter;

  public AuthController(
      AuthService authService, UserService userService, UserLookupRateLimiter lookupRateLimiter) {
    this.authService = authService;
    this.userService = userService;
    this.lookupRateLimiter = lookupRateLimiter;
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
  public ResponseEntity<UserLookupResponse> lookupUser(
      Authentication authentication, @RequestParam String email) {
    lookupRateLimiter.checkEmailLookup(authentication);
    return ResponseEntity.ok(userService.lookupByEmail(email));
  }

  @GetMapping("/users/by-id/{id}")
  public ResponseEntity<UserLookupResponse> lookupUserById(
      Authentication authentication, @PathVariable UUID id) {
    lookupRateLimiter.checkIdLookup(authentication);
    return ResponseEntity.ok(userService.lookupById(id));
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
