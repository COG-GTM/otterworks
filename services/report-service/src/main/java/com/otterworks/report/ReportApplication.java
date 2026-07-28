package com.otterworks.report;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * OtterWorks Report Service — generates PDF, CSV, and Excel reports
 * from analytics and audit data.
 *
 * Runs on Java 17 / Spring Boot 3.2.
 *
 * REMAINING TECH DEBT (follow-ups):
 * - java.util.Date usage (target: java.time.*)
 * - RestTemplate (target: RestClient)
 * - iText 5 (AGPL license; target: OpenPDF or iText 7)
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
