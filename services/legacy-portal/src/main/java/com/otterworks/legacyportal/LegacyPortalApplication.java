package com.otterworks.legacyportal;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.security.servlet.UserDetailsServiceAutoConfiguration;

/**
 * OtterWorks Legacy Portal — a modular monolith.
 *
 * <p>Three bounded contexts (announcements, user-preferences, feedback) are bundled into a single
 * deployable, each living in its own package with its own routes and its own database schema. This
 * is a deliberate decomposition candidate: the module seams map cleanly onto future microservices.
 */
// Callers authenticate with auth-service JWTs only; no generated in-memory user.
@SpringBootApplication(exclude = UserDetailsServiceAutoConfiguration.class)
public class LegacyPortalApplication {

    public static void main(String[] args) {
        SpringApplication.run(LegacyPortalApplication.class, args);
    }
}
