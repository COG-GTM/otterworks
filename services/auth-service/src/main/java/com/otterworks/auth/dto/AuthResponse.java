package com.otterworks.auth.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class AuthResponse {
  private String accessToken;

  @JsonInclude(JsonInclude.Include.NON_NULL)
  private String refreshToken;

  private String tokenType;
  private long expiresIn;
  private UserDto user;

  @Data
  @AllArgsConstructor
  public static class UserDto {
    private String id;
    private String email;
    private String displayName;
    private String avatarUrl;
  }
}
