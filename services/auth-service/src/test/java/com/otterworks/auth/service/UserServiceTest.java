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
    user.setEmail("u@otterworks.dev");
    user.setDisplayName("Original");
    user.setAvatarUrl("https://cdn/old.png");
    user.setRoles(Set.of(User.Role.USER));
  }

  @Test
  void getProfile_shouldReturnDto() {
    when(userRepository.findById(user.getId())).thenReturn(Optional.of(user));

    UserDTO dto = userService.getProfile(user.getId());

    assertThat(dto.getId()).isEqualTo(user.getId().toString());
    assertThat(dto.getRoles()).containsExactly("USER");
  }

  @Test
  void getProfile_shouldThrowWhenUserMissing() {
    UUID id = UUID.randomUUID();
    when(userRepository.findById(id)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.getProfile(id))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessage("User not found");
  }

  @Test
  void updateProfile_shouldUpdateBothFields() {
    when(userRepository.findById(user.getId())).thenReturn(Optional.of(user));
    when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));
    UpdateProfileRequest req = new UpdateProfileRequest();
    req.setDisplayName("New");
    req.setAvatarUrl("https://cdn/new.png");

    UserDTO dto = userService.updateProfile(user.getId(), req);

    assertThat(dto.getDisplayName()).isEqualTo("New");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn/new.png");
  }

  @Test
  void updateProfile_shouldLeaveFieldsUnchangedWhenNull() {
    when(userRepository.findById(user.getId())).thenReturn(Optional.of(user));
    when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));

    UserDTO dto = userService.updateProfile(user.getId(), new UpdateProfileRequest());

    assertThat(dto.getDisplayName()).isEqualTo("Original");
    assertThat(dto.getAvatarUrl()).isEqualTo("https://cdn/old.png");
  }

  @Test
  void updateProfile_shouldThrowWhenUserMissing() {
    UUID id = UUID.randomUUID();
    when(userRepository.findById(id)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.updateProfile(id, new UpdateProfileRequest()))
        .isInstanceOf(IllegalArgumentException.class);
    verify(userRepository, never()).save(any());
  }

  @Test
  void listUsers_shouldMapPage() {
    Pageable pageable = PageRequest.of(0, 10);
    when(userRepository.findAll(pageable)).thenReturn(new PageImpl<>(List.of(user), pageable, 1));

    assertThat(userService.listUsers(pageable).getContent())
        .extracting(UserDTO::getEmail)
        .containsExactly("u@otterworks.dev");
  }

  @Test
  void findByEmail_shouldReturnDto() {
    when(userRepository.findByEmail("u@otterworks.dev")).thenReturn(Optional.of(user));

    assertThat(userService.findByEmail("u@otterworks.dev").getDisplayName()).isEqualTo("Original");
  }

  @Test
  void findByEmail_shouldThrowWhenMissing() {
    when(userRepository.findByEmail("x@otterworks.dev")).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.findByEmail("x@otterworks.dev"))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("x@otterworks.dev");
  }
}
