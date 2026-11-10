package com.otterworks.auth.audit;

import com.otterworks.auth.entity.User;
import java.util.Set;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

/** Resolves the "who" of an audit event. */
public final class AuditActor {

  public static final String TYPE_USER = "user";
  public static final String TYPE_ADMIN = "admin";
  public static final String TYPE_ANONYMOUS = "anonymous";

  private static final Set<String> ADMIN_AUTHORITIES = Set.of("ROLE_ADMIN", "ROLE_OWNER");

  private AuditActor() {}

  public static String typeOf(User user) {
    Set<User.Role> roles = user.getRoles();
    return roles != null && (roles.contains(User.Role.ADMIN) || roles.contains(User.Role.OWNER))
        ? TYPE_ADMIN
        : TYPE_USER;
  }

  /** The authenticated principal (user id) of the current request, or {@code anonymous}. */
  public static String currentUserId() {
    Authentication auth = SecurityContextHolder.getContext().getAuthentication();
    if (auth == null || !(auth.getPrincipal() instanceof String principal) || principal.isBlank()) {
      return AuditEvent.ANONYMOUS;
    }
    return "anonymousUser".equals(principal) ? AuditEvent.ANONYMOUS : principal;
  }

  public static String currentActorType() {
    Authentication auth = SecurityContextHolder.getContext().getAuthentication();
    if (AuditEvent.ANONYMOUS.equals(currentUserId())) {
      return TYPE_ANONYMOUS;
    }
    for (GrantedAuthority authority : auth.getAuthorities()) {
      if (ADMIN_AUTHORITIES.contains(authority.getAuthority())) {
        return TYPE_ADMIN;
      }
    }
    return TYPE_USER;
  }
}
