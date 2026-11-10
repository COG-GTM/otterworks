package com.otterworks.auth.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class UpdateProfileRequest {
  @Size(min = 1, max = 100)
  private String displayName;

  @Size(max = 500)
  private String avatarUrl;

  @Email
  @Size(max = 255)
  private String email;
}
