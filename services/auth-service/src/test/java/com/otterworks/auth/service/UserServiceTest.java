package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.otterworks.auth.dto.UpdateProfileRequest;
import com.otterworks.auth.dto.UserDTO;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.UserRepository;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;

@ExtendWith(MockitoExtension.class)
class UserServiceTest {

  @Mock private UserRepository userRepository;

  @InjectMocks private UserService userService;

  private UUID userId;
  private User user;

  @BeforeEach
  void setUp() {
    userId = UUID.fromString("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
    user = new User();
    user.setId(userId);
    user.setEmail("profile@otterworks.dev");
    user.setDisplayName("Profile User");
    user.setAvatarUrl("https://cdn.otterworks.dev/a.png");
    user.setEmailVerified(true);
    user.setRoles(Set.of(User.Role.USER, User.Role.EDITOR));
    user.setLastLoginAt(Instant.parse("2024-01-01T00:00:00Z"));
  }

  @Test
  void getProfile_shouldMapEntityToDto() {
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));

    UserDTO dto = userService.getProfile(userId);

    assertThat(dto.getId()).isEqualTo(userId.toString());
    assertThat(dto.getEmail()).isEqualTo("profile@otterworks.dev");
    assertThat(dto.getDisplayName()).isEqualTo("Profile User");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/a.png");
    assertThat(dto.isEmailVerified()).isTrue();
    assertThat(dto.getRoles()).containsExactlyInAnyOrder("USER", "EDITOR");
    assertThat(dto.getLastLoginAt()).isEqualTo(Instant.parse("2024-01-01T00:00:00Z"));
  }

  @Test
  void getProfile_shouldRejectUnknownUser() {
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.getProfile(userId))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
  }

  @Test
  void updateProfile_shouldUpdateBothFields() {
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(userRepository.save(user)).thenReturn(user);

    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("Renamed");
    request.setAvatarUrl("https://cdn.otterworks.dev/b.png");

    UserDTO dto = userService.updateProfile(userId, request);

    assertThat(dto.getDisplayName()).isEqualTo("Renamed");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/b.png");
  }

  @Test
  void updateProfile_shouldUpdateDisplayNameOnly() {
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(userRepository.save(user)).thenReturn(user);

    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("Only Name");

    UserDTO dto = userService.updateProfile(userId, request);

    assertThat(dto.getDisplayName()).isEqualTo("Only Name");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/a.png");
  }

  @Test
  void updateProfile_shouldUpdateAvatarOnly() {
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(userRepository.save(user)).thenReturn(user);

    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setAvatarUrl("https://cdn.otterworks.dev/c.png");

    UserDTO dto = userService.updateProfile(userId, request);

    assertThat(dto.getDisplayName()).isEqualTo("Profile User");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/c.png");
  }

  @Test
  void updateProfile_shouldIgnoreEmptyRequest() {
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(userRepository.save(user)).thenReturn(user);

    UserDTO dto = userService.updateProfile(userId, new UpdateProfileRequest());

    assertThat(dto.getDisplayName()).isEqualTo("Profile User");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/a.png");
  }

  @Test
  void updateProfile_shouldRejectUnknownUser() {
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.updateProfile(userId, new UpdateProfileRequest()))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(userRepository, never()).save(any(User.class));
  }

  @Test
  void listUsers_shouldMapEveryPageElement() {
    Pageable pageable = PageRequest.of(0, 10);
    when(userRepository.findAll(pageable)).thenReturn(new PageImpl<>(List.of(user), pageable, 1));

    Page<UserDTO> page = userService.listUsers(pageable);

    assertThat(page.getTotalElements()).isEqualTo(1);
    assertThat(page.getContent())
        .singleElement()
        .satisfies(dto -> assertThat(dto.getEmail()).isEqualTo("profile@otterworks.dev"));
  }

  @Test
  void findByEmail_shouldReturnDto() {
    when(userRepository.findByEmail("profile@otterworks.dev")).thenReturn(Optional.of(user));

    UserDTO dto = userService.findByEmail("profile@otterworks.dev");

    assertThat(dto.getId()).isEqualTo(userId.toString());
  }

  @Test
  void findByEmail_shouldRejectUnknownEmail() {
    when(userRepository.findByEmail("missing@otterworks.dev")).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.findByEmail("missing@otterworks.dev"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found with email: missing@otterworks.dev");
  }
}
