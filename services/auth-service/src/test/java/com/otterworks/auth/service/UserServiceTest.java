package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.otterworks.auth.dto.UserDTO;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.UserRepository;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class UserServiceTest {

  @Mock private UserRepository userRepository;

  @InjectMocks private UserService userService;

  private User testUser;
  private UUID userId;

  @BeforeEach
  void setUp() {
    userId = UUID.randomUUID();
    testUser = new User();
    testUser.setId(userId);
    testUser.setEmail("test@otterworks.dev");
    testUser.setDisplayName("Test User");
    testUser.setPasswordHash("$2a$12$encodedpassword");
    testUser.setRoles(Set.of(User.Role.USER));
  }

  @Test
  void getProfile_shouldIncludeDefaultQuotaBytes() {
    when(userRepository.findById(userId)).thenReturn(Optional.of(testUser));

    UserDTO dto = userService.getProfile(userId);

    assertThat(dto.getQuotaBytes()).isEqualTo(10_737_418_240L);
  }

  @Test
  void updateQuota_shouldPersistNewQuota() {
    when(userRepository.findById(userId)).thenReturn(Optional.of(testUser));
    when(userRepository.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));

    UserDTO dto = userService.updateQuota(userId, 21_474_836_480L);

    assertThat(dto.getQuotaBytes()).isEqualTo(21_474_836_480L);
    verify(userRepository).save(testUser);
  }

  @Test
  void updateQuota_shouldThrowWhenUserNotFound() {
    when(userRepository.findById(userId)).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.updateQuota(userId, 1L))
        .isInstanceOf(IllegalArgumentException.class);
  }
}
