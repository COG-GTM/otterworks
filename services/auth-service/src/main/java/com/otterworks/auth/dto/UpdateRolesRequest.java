package com.otterworks.auth.dto;

import com.otterworks.auth.entity.User;
import jakarta.validation.constraints.NotEmpty;
import java.util.Set;
import lombok.Data;

@Data
public class UpdateRolesRequest {
  @NotEmpty private Set<User.Role> roles;
}
