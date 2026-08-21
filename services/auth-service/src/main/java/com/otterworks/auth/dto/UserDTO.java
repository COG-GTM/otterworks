package com.otterworks.auth.dto;

import com.otterworks.auth.entity.User;
import java.time.Instant;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@AllArgsConstructor
@NoArgsConstructor
public class UserDTO {
  private String id;
  private String email;
  private String displayName;
  private String avatarUrl;
  private Set<String> roles;
  private boolean emailVerified;
  private Instant createdAt;
  private Instant updatedAt;
  private Instant lastLoginAt;
  private long quotaBytes;

  public static UserDTO fromEntity(User user) {
    UserDTO dto = new UserDTO();
    dto.setId(user.getId().toString());
    dto.setEmail(user.getEmail());
    dto.setDisplayName(user.getDisplayName());
    dto.setAvatarUrl(user.getAvatarUrl());
    dto.setRoles(user.getRoles().stream().map(Enum::name).collect(Collectors.toSet()));
    dto.setEmailVerified(user.isEmailVerified());
    dto.setCreatedAt(user.getCreatedAt());
    dto.setUpdatedAt(user.getUpdatedAt());
    dto.setLastLoginAt(user.getLastLoginAt());
    dto.setQuotaBytes(user.getQuotaBytes());
    return dto;
  }
}
