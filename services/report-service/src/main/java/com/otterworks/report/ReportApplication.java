package com.otterworks.report;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * OtterWorks Report Service — generates PDF, CSV, and Excel reports
 * from analytics and audit data.
 *
 * REMAINING TECH DEBT (tracked in UPGRADE_GUIDE.md):
 * - java.util.Date usage (target: java.time.*)
 * - RestTemplate (target: WebClient or RestClient)
 * - iText 5 (AGPL license; target: OpenPDF or iText 7)
 * - Apache POI 4.x (target: 5.2+)
 * - Guava 28 (multiple CVEs; target: 33+)
 * - Commons IO 2.6 (target: 2.15+), OpenCSV 4.6 (target: 5.9+)
 */
@SpringBootApplication
@EnableScheduling
@EnableAsync
public class ReportApplication {

    public static void main(String[] args) {
        SpringApplication.run(ReportApplication.class, args);
    }
}
