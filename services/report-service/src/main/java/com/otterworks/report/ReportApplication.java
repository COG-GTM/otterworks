package com.otterworks.report;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * OtterWorks Report Service — generates PDF, CSV, and Excel reports
 * from analytics and audit data.
 *
 * Runs on Java 17 / Spring Boot 3.5 (jakarta.*, Spring Security 6, Hibernate 6,
 * springdoc-openapi 2, Apache HttpClient 5).
 *
 * Remaining tech debt:
 * - java.util.Date usage (target: java.time.*)
 * - RestTemplate (target: RestClient)
 */
@SpringBootApplication
@EnableScheduling
@EnableAsync
public class ReportApplication {

    public static void main(String[] args) {
        SpringApplication.run(ReportApplication.class, args);
    }
}
