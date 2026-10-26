package com.otterworks.auth.bootstrap;

import com.otterworks.auth.entity.User;
import com.otterworks.auth.repository.UserRepository;
import java.util.Optional;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

/**
 * Creates the first administrator from deployment-supplied credentials. Does nothing unless both
 * BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD are set, and never overwrites an existing
 * account.
 */
@Component
public class AdminBootstrap implements ApplicationRunner {

  static final int MIN_PASSWORD_LENGTH = 12;

  private static final Logger log = LoggerFactory.getLogger(AdminBootstrap.class);

  private final UserRepository userRepository;
  private final PasswordEncoder passwordEncoder;
  private final String email;
  private final String password;

  public AdminBootstrap(
      UserRepository userRepository,
      PasswordEncoder passwordEncoder,
      @Value("${otterworks.bootstrap-admin.email:}") String email,
      @Value("${otterworks.bootstrap-admin.password:}") String password) {
    this.userRepository = userRepository;
    this.passwordEncoder = passwordEncoder;
    this.email = email;
    this.password = password;
  }

  @Override
  public void run(ApplicationArguments args) {
    if (!StringUtils.hasText(email) || !StringUtils.hasText(password)) {
      return;
    }
    if (password.length() < MIN_PASSWORD_LENGTH) {
      log.error(
          "Bootstrap admin not created: BOOTSTRAP_ADMIN_PASSWORD must be at least {} characters",
          MIN_PASSWORD_LENGTH);
      return;
    }
    String normalizedEmail = email.trim();
    Optional<User> existing = userRepository.findByEmail(normalizedEmail);
    if (existing.isPresent()) {
      if (existing.get().getRoles().contains(User.Role.ADMIN)) {
        log.info("Bootstrap admin already exists: email={}", normalizedEmail);
      } else {
        log.error(
            "Bootstrap admin not created: email={} belongs to a non-admin account;"
                + " choose a different BOOTSTRAP_ADMIN_EMAIL",
            normalizedEmail);
      }
      return;
    }

    User admin = new User();
    admin.setEmail(normalizedEmail);
    admin.setPasswordHash(passwordEncoder.encode(password));
    admin.setDisplayName("Administrator");
    admin.setEmailVerified(true);
    admin.setRoles(Set.of(User.Role.ADMIN, User.Role.USER));
    userRepository.save(admin);
    log.info("Bootstrap admin created: email={}", normalizedEmail);
  }
}
