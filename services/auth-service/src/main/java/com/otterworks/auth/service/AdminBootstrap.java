package com.otterworks.auth.service;

import com.otterworks.auth.config.AdminBootstrapProperties;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * Provisions the initial admin account from configuration so no credential is committed to the
 * repository. Creates the account if missing, or sets its password if it was revoked; an existing
 * usable password is never overwritten.
 */
@Component
public class AdminBootstrap implements ApplicationRunner {

  public static final UUID ADMIN_ID = UUID.fromString("a0000000-0000-0000-0000-000000000001");
  static final String REVOKED_PASSWORD_HASH = "!";

  private static final Logger log = LoggerFactory.getLogger(AdminBootstrap.class);

  private final AdminBootstrapProperties properties;
  private final JdbcTemplate jdbcTemplate;
  private final PasswordEncoder passwordEncoder;

  public AdminBootstrap(
      AdminBootstrapProperties properties,
      JdbcTemplate jdbcTemplate,
      PasswordEncoder passwordEncoder) {
    this.properties = properties;
    this.jdbcTemplate = jdbcTemplate;
    this.passwordEncoder = passwordEncoder;
  }

  @Override
  @Transactional
  public void run(ApplicationArguments args) {
    String password = properties.getPassword();
    if (password == null || password.isBlank()) {
      log.info("ADMIN_BOOTSTRAP_PASSWORD not set; skipping admin account provisioning");
      return;
    }

    List<String> hashes =
        jdbcTemplate.queryForList(
            "SELECT password_hash FROM users WHERE id = ?", String.class, ADMIN_ID);

    if (hashes.isEmpty()) {
      createAdmin(password);
    } else if (REVOKED_PASSWORD_HASH.equals(hashes.get(0))) {
      jdbcTemplate.update(
          "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
          passwordEncoder.encode(password),
          Timestamp.from(Instant.now()),
          ADMIN_ID);
      log.info("Admin account password provisioned: id={}", ADMIN_ID);
    }
  }

  private void createAdmin(String password) {
    Integer emailTaken =
        jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM users WHERE email = ?", Integer.class, properties.getEmail());
    if (emailTaken != null && emailTaken > 0) {
      log.warn(
          "Admin bootstrap skipped: email {} already belongs to another user",
          properties.getEmail());
      return;
    }

    Timestamp now = Timestamp.from(Instant.now());
    jdbcTemplate.update(
        "INSERT INTO users (id, email, password_hash, display_name, email_verified, mfa_enabled,"
            + " created_at, updated_at) VALUES (?, ?, ?, ?, true, false, ?, ?)",
        ADMIN_ID,
        properties.getEmail(),
        passwordEncoder.encode(password),
        properties.getDisplayName(),
        now,
        now);
    for (String role : List.of("ADMIN", "USER")) {
      jdbcTemplate.update("INSERT INTO user_roles (user_id, role) VALUES (?, ?)", ADMIN_ID, role);
    }
    log.info("Admin account created: id={}, email={}", ADMIN_ID, properties.getEmail());
  }
}
