package com.otterworks.announcements;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** Announcements bounded context, extracted from legacy-portal. Owns the {@code announcements} schema. */
@SpringBootApplication
public class AnnouncementsServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(AnnouncementsServiceApplication.class, args);
    }
}
