package com.otterworks.report;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * OtterWorks Report Service — generates PDF, CSV, and Excel reports
 * from analytics and audit data.
 *
 * REMAINING TECH DEBT (out of scope for the Java 17 / Boot 3.2 migration):
 * - java.util.Date usage (target: java.time.*)
 * - RestTemplate (target: WebClient or RestClient)
 * - OpenCSV 4.6 (target: 5.9+)
 */
@SpringBootApplication
@EnableScheduling
@EnableAsync
public class ReportApplication {

    public static void main(String[] args) {
        SpringApplication.run(ReportApplication.class, args);
    }
}
