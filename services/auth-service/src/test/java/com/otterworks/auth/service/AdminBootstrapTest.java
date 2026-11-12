package com.otterworks.auth.service;

import static org.assertj.core.api.Assertions.assertThat;

import com.otterworks.auth.config.AdminBootstrapProperties;
import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.RefreshTokenRepository;
import com.otterworks.auth.repository.UserRepository;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.context.ActiveProfiles;

@SpringBootTest
@ActiveProfiles("test")
class AdminBootstrapTest {

  private static final String PASSWORD = "bootstrap-test-password";

  @Autowired private AdminBootstrap adminBootstrap;
  @Autowired private AdminBootstrapProperties properties;
  @Autowired private UserRepository userRepository;
  @Autowired private RefreshTokenRepository refreshTokenRepository;
  @Autowired private JdbcTemplate jdbcTemplate;
  @Autowired private PasswordEncoder passwordEncoder;

  @BeforeEach
  void setUp() {
    refreshTokenRepository.deleteAll();
    userRepository.deleteAll();
    properties.setPassword(PASSWORD);
  }

  @AfterEach
  void tearDown() {
    properties.setPassword(null);
  }

  @Test
  void run_withoutPassword_shouldNotCreateAdmin() {
    properties.setPassword("");

    adminBootstrap.run(null);

    assertThat(userRepository.findById(AdminBootstrap.ADMIN_ID)).isEmpty();
  }

  @Test
  void run_whenAdminMissing_shouldCreateAdminWithConfiguredPassword() {
    adminBootstrap.run(null);

    User admin = userRepository.findById(AdminBootstrap.ADMIN_ID).orElseThrow();
    assertThat(admin.getEmail()).isEqualTo(properties.getEmail());
    assertThat(passwordEncoder.matches(PASSWORD, admin.getPasswordHash())).isTrue();
    assertThat(admin.getRoles()).containsExactlyInAnyOrder(User.Role.ADMIN, User.Role.USER);
  }

  @Test
  void run_whenAdminPasswordRevoked_shouldSetConfiguredPassword() {
    adminBootstrap.run(null);
    jdbcTemplate.update(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        AdminBootstrap.REVOKED_PASSWORD_HASH,
        AdminBootstrap.ADMIN_ID);

    adminBootstrap.run(null);

    User admin = userRepository.findById(AdminBootstrap.ADMIN_ID).orElseThrow();
    assertThat(passwordEncoder.matches(PASSWORD, admin.getPasswordHash())).isTrue();
  }

  @Test
  void run_whenAdminHasPassword_shouldNotOverwriteIt() {
    adminBootstrap.run(null);
    String rotated = passwordEncoder.encode("rotated-password");
    jdbcTemplate.update(
        "UPDATE users SET password_hash = ? WHERE id = ?", rotated, AdminBootstrap.ADMIN_ID);

    adminBootstrap.run(null);

    User admin = userRepository.findById(AdminBootstrap.ADMIN_ID).orElseThrow();
    assertThat(admin.getPasswordHash()).isEqualTo(rotated);
  }
}
