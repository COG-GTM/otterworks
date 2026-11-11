package com.otterworks.auth.controller;

import com.otterworks.auth.config.JwtConfig;
import com.otterworks.auth.dto.*;
import com.otterworks.auth.service.AuthService;
import com.otterworks.auth.service.UserService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

  // HttpOnly so browser scripts can never read the refresh token; scoped to the auth endpoints.
  static final String REFRESH_COOKIE_NAME = "otter_refresh_token";
  static final String REFRESH_COOKIE_PATH = "/api/v1/auth";

  private final AuthService authService;
  private final UserService userService;
  private final JwtConfig jwtConfig;
  private final boolean refreshCookieSecure;

  public AuthController(
      AuthService authService,
      UserService userService,
      JwtConfig jwtConfig,
      @Value("${auth.refresh-cookie.secure:true}") boolean refreshCookieSecure) {
    this.authService = authService;
    this.userService = userService;
    this.jwtConfig = jwtConfig;
    this.refreshCookieSecure = refreshCookieSecure;
  }

  @PostMapping("/register")
  public ResponseEntity<AuthResponse> register(@Valid @RequestBody RegisterRequest request) {
    AuthResponse response = authService.register(request);
    return ResponseEntity.status(HttpStatus.CREATED)
        .header(HttpHeaders.SET_COOKIE, refreshCookie(response.getRefreshToken()).toString())
        .body(response);
  }

  @PostMapping("/login")
  public ResponseEntity<AuthResponse> login(@Valid @RequestBody LoginRequest request) {
    AuthResponse response = authService.login(request);
    return ResponseEntity.ok()
        .header(HttpHeaders.SET_COOKIE, refreshCookie(response.getRefreshToken()).toString())
        .body(response);
  }

  @PostMapping("/refresh")
  public ResponseEntity<AuthResponse> refresh(
      @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String bearerToken,
      @CookieValue(value = REFRESH_COOKIE_NAME, required = false) String cookieToken) {
    if (cookieToken != null && !cookieToken.isBlank()) {
      // Cookie-based (browser) refresh: rotate the cookie and never echo the refresh token
      // into a response body that page scripts can read.
      AuthResponse response = authService.refreshToken(cookieToken);
      String rotated = response.getRefreshToken();
      response.setRefreshToken(null);
      return ResponseEntity.ok()
          .header(HttpHeaders.SET_COOKIE, refreshCookie(rotated).toString())
          .body(response);
    }
    if (bearerToken == null || !bearerToken.startsWith("Bearer ")) {
      return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
    }
    AuthResponse response = authService.refreshToken(bearerToken.substring("Bearer ".length()));
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
        .header(HttpHeaders.SET_COOKIE, clearedRefreshCookie().toString())
        .build();
  }

  private ResponseCookie refreshCookie(String refreshToken) {
    return refreshCookieBuilder(refreshToken).maxAge(jwtConfig.getRefreshTokenExpiry()).build();
  }

  private ResponseCookie clearedRefreshCookie() {
    return refreshCookieBuilder("").maxAge(0).build();
  }

  private ResponseCookie.ResponseCookieBuilder refreshCookieBuilder(String value) {
    return ResponseCookie.from(REFRESH_COOKIE_NAME, value)
        .httpOnly(true)
        .secure(refreshCookieSecure)
        .sameSite("Strict")
        .path(REFRESH_COOKIE_PATH);
  }
}
