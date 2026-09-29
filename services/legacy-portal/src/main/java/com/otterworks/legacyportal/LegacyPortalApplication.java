package com.otterworks.legacyportal;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * OtterWorks Legacy Portal — a modular monolith.
 *
 * <p>The bounded contexts not yet extracted (user-preferences, feedback) are bundled into a single
 * deployable, each living in its own package with its own routes and its own database schema.
 * Announcements has moved to announcements-service (DECOMPOSITION.md §13).
 */
@SpringBootApplication
public class LegacyPortalApplication {

    public static void main(String[] args) {
        SpringApplication.run(LegacyPortalApplication.class, args);
    }
}
