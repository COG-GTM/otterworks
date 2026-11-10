package com.otterworks.report;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * OtterWorks Report Service — generates PDF, CSV, and Excel reports
 * from analytics and audit data.
 *
 * LEGACY NOTES (tech debt for upgrade exercise):
 * - Java 8 runtime (target: Java 17+)
 * - Spring Boot 2.5.14 (target: Spring Boot 3.2+)
 * - javax.* namespace throughout (target: jakarta.*)
 * - WebSecurityConfigurerAdapter (removed in Spring Security 6)
 * - SpringFox Swagger 2 (dead project; target: springdoc-openapi)
 * - JUnit 4 tests (target: JUnit 5 Jupiter)
 * - java.util.Date usage (target: java.time.*)
 * - RestTemplate (target: WebClient or RestClient)
 * - Commons Lang 2 (EOL; target: commons-lang3)
 * - Apache POI 4.x (target: 5.2+)
 * - Guava 28 (multiple CVEs; target: 33+)
 */
@SpringBootApplication
@EnableScheduling
@EnableAsync
public class ReportApplication {

    public static void main(String[] args) {
        SpringApplication.run(ReportApplication.class, args);
    }
}
