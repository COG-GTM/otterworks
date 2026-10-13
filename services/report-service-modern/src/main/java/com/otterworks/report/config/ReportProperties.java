package com.otterworks.report.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

import java.time.Duration;

@ConfigurationProperties(prefix = "otterworks")
public record ReportProperties(
        @DefaultValue Service analyticsService,
        @DefaultValue Service auditService,
        @DefaultValue Service authService,
        @DefaultValue Report report) {

    public record Service(String url) {
    }

    public record Report(
            @DefaultValue("/tmp/reports") String outputDir,
            @DefaultValue("50000") int maxRows,
            @DefaultValue("5000ms") Duration connectionTimeout,
            @DefaultValue("30000ms") Duration readTimeout) {
    }

    public String analyticsServiceUrl() {
        return urlOrDefault(analyticsService, "http://analytics-service:8088");
    }

    public String auditServiceUrl() {
        return urlOrDefault(auditService, "http://audit-service:8090");
    }

    public String authServiceUrl() {
        return urlOrDefault(authService, "http://auth-service:8081");
    }

    private static String urlOrDefault(Service service, String fallback) {
        return service != null && service.url() != null ? service.url() : fallback;
    }
}
