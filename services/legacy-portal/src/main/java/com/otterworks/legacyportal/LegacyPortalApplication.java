package com.otterworks.legacyportal;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * OtterWorks Legacy Portal — a modular monolith.
 *
 * <p>Every bounded context has been extracted: announcements, user-preferences and feedback are
 * served by announcements-service, preferences-service and feedback-service (DECOMPOSITION.md §13).
 * The monolith serves only portal-common's {@code /health} and the actuator endpoints.
 */
@SpringBootApplication
public class LegacyPortalApplication {

    public static void main(String[] args) {
        SpringApplication.run(LegacyPortalApplication.class, args);
    }
}
