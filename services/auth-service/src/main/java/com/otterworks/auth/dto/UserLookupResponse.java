package com.otterworks.auth.dto;

import lombok.AllArgsConstructor;
import lombok.Data;

/** Minimal identity returned to non-admin callers resolving a share recipient. */
@Data
@AllArgsConstructor
public class UserLookupResponse {
  private String id;
  private String displayName;

  public static UserLookupResponse fromUserDTO(UserDTO dto) {
    return new UserLookupResponse(dto.getId(), dto.getDisplayName());
  }
}
