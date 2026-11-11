package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.otterworks.auth.exception.BadRequestException;
import com.otterworks.auth.repository.UserRepository;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class UserServiceTest {

  @Mock private UserRepository userRepository;

  @InjectMocks private UserService userService;

  @Test
  void findByEmail_unknownEmail_doesNotEchoTheEmail() {
    when(userRepository.findByEmail("alice@example.com")).thenReturn(Optional.empty());

    assertThatThrownBy(() -> userService.findByEmail("alice@example.com"))
        .isInstanceOf(BadRequestException.class)
        .hasMessage("User not found");
  }
}
