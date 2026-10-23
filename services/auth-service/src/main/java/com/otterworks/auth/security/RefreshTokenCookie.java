package com.otterworks.auth.security;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;

/**
 * The refresh token is only ever handed to browsers as an HttpOnly cookie scoped to the auth
 * endpoints, so script running on the app origin cannot read or exfiltrate it.
 */
@Component
public class RefreshTokenCookie {

  public static final String NAME = "otter_refresh_token";
  public static final String PATH = "/api/v1/auth";

  private final boolean secure;
  private final String sameSite;
  private final long maxAgeSeconds;

  public RefreshTokenCookie(
      @Value("${auth.refresh-cookie.secure:true}") boolean secure,
      @Value("${auth.refresh-cookie.same-site:Strict}") String sameSite,
      @Value("${jwt.refresh-token-expiry:2592000}") long maxAgeSeconds) {
    this.secure = secure;
    this.sameSite = sameSite;
    this.maxAgeSeconds = maxAgeSeconds;
  }

  public ResponseCookie issue(String refreshToken) {
    return build(refreshToken, Duration.ofSeconds(maxAgeSeconds));
  }

  public ResponseCookie clear() {
    return build("", Duration.ZERO);
  }

  public String read(HttpServletRequest request) {
    Cookie[] cookies = request.getCookies();
    if (cookies == null) {
      return null;
    }
    for (Cookie cookie : cookies) {
      if (NAME.equals(cookie.getName()) && !cookie.getValue().isBlank()) {
        return cookie.getValue();
      }
    }
    return null;
  }

  private ResponseCookie build(String value, Duration maxAge) {
    return ResponseCookie.from(NAME, value)
        .httpOnly(true)
        .secure(secure)
        .sameSite(sameSite)
        .path(PATH)
        .maxAge(maxAge)
        .build();
  }
}
