package com.otterworks.auth.bootstrap;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.UserRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;

@ExtendWith(MockitoExtension.class)
class AdminBootstrapTest {

  private static final String EMAIL = "ops@example.com";
  private static final String PASSWORD = "a-long-deploy-secret";

  @Mock private UserRepository userRepository;
  @Mock private PasswordEncoder passwordEncoder;

  private AdminBootstrap bootstrap(String email, String password) {
    return new AdminBootstrap(userRepository, passwordEncoder, email, password, "Ops Admin");
  }

  @Test
  void doesNothingWhenNotConfigured() {
    assertThat(bootstrap("", "").bootstrap()).isFalse();
    verifyNoInteractions(userRepository, passwordEncoder);
  }

  @Test
  void refusesShortOrMissingPassword() {
    assertThat(bootstrap(EMAIL, "").bootstrap()).isFalse();
    assertThat(bootstrap(EMAIL, "Admin123!").bootstrap()).isFalse();
    verifyNoInteractions(userRepository, passwordEncoder);
  }

  @Test
  void skipsWhenAnAdminAlreadyExists() {
    when(userRepository.existsByRole(User.Role.ADMIN)).thenReturn(true);

    assertThat(bootstrap(EMAIL, PASSWORD).bootstrap()).isFalse();
    verify(userRepository, never()).save(any());
  }

  @Test
  void neverPromotesAnExistingAccount() {
    when(userRepository.existsByRole(User.Role.ADMIN)).thenReturn(false);
    when(userRepository.existsByEmail(EMAIL)).thenReturn(true);

    assertThat(bootstrap(EMAIL, PASSWORD).bootstrap()).isFalse();
    verify(userRepository, never()).save(any());
  }

  @Test
  void createsFirstAdminWithHashedDeploymentPassword() {
    when(userRepository.existsByRole(User.Role.ADMIN)).thenReturn(false);
    when(userRepository.existsByEmail(EMAIL)).thenReturn(false);
    when(passwordEncoder.encode(PASSWORD)).thenReturn("$2a$12$hashed");

    assertThat(bootstrap("  " + EMAIL + " ", PASSWORD).bootstrap()).isTrue();

    ArgumentCaptor<User> saved = ArgumentCaptor.forClass(User.class);
    verify(userRepository).save(saved.capture());
    assertThat(saved.getValue().getEmail()).isEqualTo(EMAIL);
    assertThat(saved.getValue().getPasswordHash()).isEqualTo("$2a$12$hashed");
    assertThat(saved.getValue().getRoles())
        .containsExactlyInAnyOrder(User.Role.ADMIN, User.Role.USER);
    assertThat(saved.getValue().isEmailVerified()).isTrue();
  }

  @Test
  void toleratesConcurrentCreation() {
    when(userRepository.existsByRole(User.Role.ADMIN)).thenReturn(false);
    when(userRepository.existsByEmail(EMAIL)).thenReturn(false);
    when(passwordEncoder.encode(PASSWORD)).thenReturn("$2a$12$hashed");
    when(userRepository.save(any())).thenThrow(new DataIntegrityViolationException("dup"));

    assertThat(bootstrap(EMAIL, PASSWORD).bootstrap()).isFalse();
  }
}
