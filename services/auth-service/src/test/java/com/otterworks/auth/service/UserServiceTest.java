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
    userId = UUID.randomUUID();
    user = new User();
    user.setId(userId);
    user.setEmail("user@otterworks.dev");
    user.setDisplayName("User One");
    user.setPasswordHash("$2a$12$hash");
    user.setRoles(Set.of(User.Role.USER));
    user.setCreatedAt(Instant.parse("2024-01-01T00:00:00Z"));
    user.setUpdatedAt(Instant.parse("2024-01-01T00:00:00Z"));
  }

  @Test
  void getProfile_mapsTheEntityToADto() {
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));

    UserDTO dto = userService.getProfile(userId);

    assertThat(dto.getId()).isEqualTo(userId.toString());
    assertThat(dto.getEmail()).isEqualTo("user@otterworks.dev");
    assertThat(dto.getRoles()).containsExactly("USER");
  }

  @Test
  void getProfile_rejectsAnUnknownUser() {
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.getProfile(userId))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
  }

  @Test
  void updateProfile_appliesBothFieldsWhenProvided() {
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(userRepository.save(user)).thenReturn(user);

    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("Renamed");
    request.setAvatarUrl("https://cdn/new.png");

    UserDTO dto = userService.updateProfile(userId, request);

    assertThat(dto.getDisplayName()).isEqualTo("Renamed");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn/new.png");
    assertThat(user.getDisplayName()).isEqualTo("Renamed");
  }

  @Test
  void updateProfile_ignoresNullDisplayName() {
    user.setAvatarUrl("https://cdn/old.png");
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(userRepository.save(user)).thenReturn(user);

    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setAvatarUrl("https://cdn/new.png");

    UserDTO dto = userService.updateProfile(userId, request);

    assertThat(dto.getDisplayName()).isEqualTo("User One");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn/new.png");
  }

  @Test
  void updateProfile_ignoresNullAvatarUrl() {
    user.setAvatarUrl("https://cdn/old.png");
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(userRepository.save(user)).thenReturn(user);

    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("Renamed");

    UserDTO dto = userService.updateProfile(userId, request);

    assertThat(dto.getDisplayName()).isEqualTo("Renamed");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn/old.png");
  }

  @Test
  void updateProfile_withAnEmptyRequestChangesNothing() {
    when(userRepository.findById(userId)).thenReturn(Optional.of(user));
    when(userRepository.save(user)).thenReturn(user);

    UserDTO dto = userService.updateProfile(userId, new UpdateProfileRequest());

    assertThat(dto.getDisplayName()).isEqualTo("User One");
    assertThat(dto.getAvatarUrl()).isNull();
  }

  @Test
  void updateProfile_rejectsAnUnknownUser() {
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.updateProfile(userId, new UpdateProfileRequest()))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
    verify(userRepository, never()).save(any());
  }

  @Test
  void listUsers_mapsEveryPageElementAndKeepsPaginationMetadata() {
    Pageable pageable = PageRequest.of(1, 2);
    when(userRepository.findAll(pageable)).thenReturn(new PageImpl<>(List.of(user), pageable, 5));

    Page<UserDTO> page = userService.listUsers(pageable);

    assertThat(page.getTotalElements()).isEqualTo(5);
    assertThat(page.getNumber()).isEqualTo(1);
    assertThat(page.getContent())
        .singleElement()
        .satisfies(
            dto -> {
              assertThat(dto.getId()).isEqualTo(userId.toString());
              assertThat(dto.getEmail()).isEqualTo("user@otterworks.dev");
            });
  }

  @Test
  void listUsers_returnsAnEmptyPageWhenThereAreNoUsers() {
    Pageable pageable = PageRequest.of(0, 20);
    when(userRepository.findAll(pageable)).thenReturn(Page.empty(pageable));

    assertThat(userService.listUsers(pageable)).isEmpty();
  }

  @Test
  void findByEmail_mapsTheMatchingUser() {
    when(userRepository.findByEmail("user@otterworks.dev")).thenReturn(Optional.of(user));

    UserDTO dto = userService.findByEmail("user@otterworks.dev");

    assertThat(dto.getId()).isEqualTo(userId.toString());
    assertThat(dto.getDisplayName()).isEqualTo("User One");
  }

  @Test
  void findByEmail_namesTheMissingEmailInTheError() {
    when(userRepository.findByEmail("ghost@otterworks.dev")).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.findByEmail("ghost@otterworks.dev"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found with email: ghost@otterworks.dev");
  }
}
