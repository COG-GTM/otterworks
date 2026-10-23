package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.otterworks.auth.dto.UpdateProfileRequest;
import com.otterworks.auth.dto.UserDTO;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.UserRepository;
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
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;

@ExtendWith(MockitoExtension.class)
class UserServiceTest {

  @Mock private UserRepository userRepository;

  @InjectMocks private UserService userService;

  private User user;

  @BeforeEach
  void setUp() {
    user = new User();
    user.setId(UUID.randomUUID());
    user.setEmail("profile@otterworks.dev");
    user.setDisplayName("Profile User");
    user.setAvatarUrl("https://cdn.otterworks.dev/a.png");
    user.setRoles(Set.of(User.Role.USER, User.Role.EDITOR));
  }

  @Test
  void getProfile_returnsMappedDto() {
    when(userRepository.findById(user.getId())).thenReturn(Optional.of(user));

    UserDTO dto = userService.getProfile(user.getId());

    assertThat(dto.getId()).isEqualTo(user.getId().toString());
    assertThat(dto.getEmail()).isEqualTo("profile@otterworks.dev");
    assertThat(dto.getDisplayName()).isEqualTo("Profile User");
    assertThat(dto.getRoles()).containsExactlyInAnyOrder("USER", "EDITOR");
    assertThat(dto.isEmailVerified()).isFalse();
  }

  @Test
  void getProfile_unknownUserThrows() {
    UUID id = UUID.randomUUID();
    when(userRepository.findById(id)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.getProfile(id))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
  }

  @Test
  void updateProfile_updatesOnlyProvidedFields() {
    when(userRepository.findById(user.getId())).thenReturn(Optional.of(user));
    when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setDisplayName("Renamed");

    UserDTO dto = userService.updateProfile(user.getId(), request);

    assertThat(dto.getDisplayName()).isEqualTo("Renamed");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/a.png");
    verify(userRepository).save(user);
  }

  @Test
  void updateProfile_updatesAvatarWhenProvided() {
    when(userRepository.findById(user.getId())).thenReturn(Optional.of(user));
    when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));
    UpdateProfileRequest request = new UpdateProfileRequest();
    request.setAvatarUrl("https://cdn.otterworks.dev/b.png");

    UserDTO dto = userService.updateProfile(user.getId(), request);

    assertThat(dto.getDisplayName()).isEqualTo("Profile User");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn.otterworks.dev/b.png");
  }

  @Test
  void updateProfile_unknownUserThrowsAndDoesNotSave() {
    UUID id = UUID.randomUUID();
    when(userRepository.findById(id)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.updateProfile(id, new UpdateProfileRequest()))
        .isInstanceOf(IllegalArgumentException.class);
    verify(userRepository, never()).save(any());
  }

  @Test
  void findByEmail_returnsUser() {
    when(userRepository.findByEmail("profile@otterworks.dev")).thenReturn(Optional.of(user));

    assertThat(userService.findByEmail("profile@otterworks.dev").getId())
        .isEqualTo(user.getId().toString());
  }

  @Test
  void findByEmail_unknownEmailThrows() {
    when(userRepository.findByEmail("nobody@otterworks.dev")).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.findByEmail("nobody@otterworks.dev"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageStartingWith("User not found");
  }

  @Test
  void listUsers_mapsPage() {
    Pageable pageable = PageRequest.of(0, 10);
    when(userRepository.findAll(pageable)).thenReturn(new PageImpl<>(List.of(user), pageable, 1));

    var page = userService.listUsers(pageable);

    assertThat(page.getTotalElements()).isEqualTo(1);
    assertThat(page.getContent().get(0).getEmail()).isEqualTo("profile@otterworks.dev");
  }
}
