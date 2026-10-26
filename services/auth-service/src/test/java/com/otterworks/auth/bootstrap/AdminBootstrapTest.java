package com.otterworks.auth.bootstrap;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.UserRepository;
import java.util.HashSet;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

@ExtendWith(MockitoExtension.class)
class AdminBootstrapTest {

  private static final String EMAIL = "ops@example.com";
  private static final String PASSWORD = "a-long-random-password";

  @Mock private UserRepository userRepository;
  @Mock private PasswordEncoder passwordEncoder;

  private AdminBootstrap bootstrap(String email, String password) {
    return new AdminBootstrap(userRepository, passwordEncoder, email, password);
  }

  @Test
  void run_withoutCredentials_createsNothing() {
    bootstrap("", "").run(null);
    bootstrap(EMAIL, "").run(null);
    bootstrap("", PASSWORD).run(null);

    verifyNoInteractions(userRepository, passwordEncoder);
  }

  @Test
  void run_withShortPassword_createsNothing() {
    bootstrap(EMAIL, "short").run(null);

    verifyNoInteractions(userRepository, passwordEncoder);
  }

  @Test
  void run_whenAdminExists_doesNotOverwrite() {
    when(userRepository.findByEmail(EMAIL)).thenReturn(Optional.of(userWith(User.Role.ADMIN)));

    bootstrap(EMAIL, PASSWORD).run(null);

    verify(userRepository, never()).save(any());
    verifyNoInteractions(passwordEncoder);
  }

  @Test
  void run_whenNonAdminOwnsEmail_doesNotPromote() {
    User existing = userWith(User.Role.USER);
    when(userRepository.findByEmail(EMAIL)).thenReturn(Optional.of(existing));

    bootstrap(EMAIL, PASSWORD).run(null);

    verify(userRepository, never()).save(any());
    verifyNoInteractions(passwordEncoder);
    assertThat(existing.getRoles()).containsExactly(User.Role.USER);
  }

  private static User userWith(User.Role role) {
    User user = new User();
    user.setEmail(EMAIL);
    user.setRoles(new HashSet<>(Set.of(role)));
    return user;
  }

  @Test
  void run_withCredentials_createsAdmin() {
    when(userRepository.findByEmail(EMAIL)).thenReturn(Optional.empty());
    when(passwordEncoder.encode(PASSWORD)).thenReturn("$2a$12$encoded");

    bootstrap(" " + EMAIL + " ", PASSWORD).run(null);

    ArgumentCaptor<User> captor = ArgumentCaptor.forClass(User.class);
    verify(userRepository).save(captor.capture());
    User saved = captor.getValue();
    assertThat(saved.getEmail()).isEqualTo(EMAIL);
    assertThat(saved.getPasswordHash()).isEqualTo("$2a$12$encoded");
    assertThat(saved.getRoles()).containsExactlyInAnyOrder(User.Role.ADMIN, User.Role.USER);
  }
}
