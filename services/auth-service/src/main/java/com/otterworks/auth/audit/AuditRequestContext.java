package com.otterworks.auth.audit;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

/** "From where" of an audit event, read from the current HTTP request (if any). */
public record AuditRequestContext(String ipAddress, String userAgent, String requestId) {

  static final AuditRequestContext NONE = new AuditRequestContext(null, null, null);

  public static AuditRequestContext current() {
    RequestAttributes attributes = RequestContextHolder.getRequestAttributes();
    if (!(attributes instanceof ServletRequestAttributes servletAttributes)) {
      return NONE;
    }
    return from(servletAttributes.getRequest());
  }

  public static AuditRequestContext from(HttpServletRequest request) {
    return new AuditRequestContext(
        clientIp(request),
        blankToNull(request.getHeader("User-Agent")),
        blankToNull(request.getHeader("X-Request-ID")));
  }

  static String clientIp(HttpServletRequest request) {
    String forwardedFor = request.getHeader("X-Forwarded-For");
    if (forwardedFor != null) {
      String first = forwardedFor.split(",", 2)[0].trim();
      if (!first.isEmpty()) {
        return first;
      }
    }
    String realIp = blankToNull(request.getHeader("X-Real-IP"));
    return realIp != null ? realIp.trim() : request.getRemoteAddr();
  }

  private static String blankToNull(String value) {
    return value == null || value.isBlank() ? null : value;
  }
}
