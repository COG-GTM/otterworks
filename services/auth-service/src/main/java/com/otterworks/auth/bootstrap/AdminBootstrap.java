package com.otterworks.auth.bootstrap;

import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.UserRepository;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

/**
 * Creates the first administrator from deployment-supplied credentials. Runs only when
 * AUTH_BOOTSTRAP_ADMIN_EMAIL and AUTH_BOOTSTRAP_ADMIN_PASSWORD are set and no ADMIN exists yet; it
 * never promotes an existing account.
 */
@Component
public class AdminBootstrap implements ApplicationRunner {

  private static final Logger log = LoggerFactory.getLogger(AdminBootstrap.class);

  static final int MIN_PASSWORD_LENGTH = 12;

  private final UserRepository userRepository;
  private final PasswordEncoder passwordEncoder;
  private final String email;
  private final String password;
  private final String displayName;

  public AdminBootstrap(
      UserRepository userRepository,
      PasswordEncoder passwordEncoder,
      @Value("${auth.bootstrap-admin.email:}") String email,
      @Value("${auth.bootstrap-admin.password:}") String password,
      @Value("${auth.bootstrap-admin.display-name:Administrator}") String displayName) {
    this.userRepository = userRepository;
    this.passwordEncoder = passwordEncoder;
    this.email = email == null ? "" : email.trim();
    this.password = password == null ? "" : password;
    this.displayName = displayName;
  }

  @Override
  public void run(ApplicationArguments args) {
    bootstrap();
  }

  boolean bootstrap() {
    if (email.isEmpty()) {
      return false;
    }
    if (password.length() < MIN_PASSWORD_LENGTH) {
      log.warn(
          "Admin bootstrap skipped: AUTH_BOOTSTRAP_ADMIN_PASSWORD must be at least {} characters",
          MIN_PASSWORD_LENGTH);
      return false;
    }
    if (userRepository.existsByRole(User.Role.ADMIN)) {
      log.info("Admin bootstrap skipped: an administrator already exists");
      return false;
    }
    if (userRepository.existsByEmail(email)) {
      log.warn(
          "Admin bootstrap skipped: an account with the bootstrap email already exists and will"
              + " not be promoted");
      return false;
    }

    User admin = new User();
    admin.setEmail(email);
    admin.setPasswordHash(passwordEncoder.encode(password));
    admin.setDisplayName(displayName);
    admin.setEmailVerified(true);
    admin.setRoles(Set.of(User.Role.ADMIN, User.Role.USER));
    try {
      userRepository.save(admin);
    } catch (DataIntegrityViolationException e) {
      log.info("Admin bootstrap skipped: account was created concurrently");
      return false;
    }
    log.info("Bootstrapped administrator account: email={}", email);
    return true;
  }
}
