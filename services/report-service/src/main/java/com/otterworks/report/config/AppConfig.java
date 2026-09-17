package com.otterworks.report.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import org.apache.hc.client5.http.config.RequestConfig;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager;
import org.apache.hc.core5.util.Timeout;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

/**
 * Application configuration for external service URLs and report generation.
 */
@Configuration
public class AppConfig {

    @Value("${otterworks.analytics-service.url:http://analytics-service:8088}")
    private String analyticsServiceUrl;

    @Value("${otterworks.audit-service.url:http://audit-service:8090}")
    private String auditServiceUrl;

    @Value("${otterworks.auth-service.url:http://auth-service:8081}")
    private String authServiceUrl;

    @Value("${otterworks.report.output-dir:/tmp/reports}")
    private String reportOutputDir;

    @Value("${otterworks.report.max-rows:50000}")
    private int maxRows;

    @Value("${otterworks.report.connection-timeout:5000}")
    private int connectionTimeout;

    @Value("${otterworks.report.read-timeout:30000}")
    private int readTimeout;

    @Bean
    public RestTemplate restTemplate() {
        PoolingHttpClientConnectionManager connectionManager = new PoolingHttpClientConnectionManager();
        connectionManager.setMaxTotal(50);
        connectionManager.setDefaultMaxPerRoute(20);

        CloseableHttpClient httpClient = HttpClients.custom()
                .setConnectionManager(connectionManager)
                .setDefaultRequestConfig(RequestConfig.custom()
                        .setConnectionRequestTimeout(Timeout.ofMilliseconds(connectionTimeout))
                        .setResponseTimeout(Timeout.ofMilliseconds(readTimeout))
                        .build())
                .build();

        HttpComponentsClientHttpRequestFactory factory = new HttpComponentsClientHttpRequestFactory(httpClient);
        factory.setConnectTimeout(java.time.Duration.ofMillis(connectionTimeout));
        factory.setConnectionRequestTimeout(java.time.Duration.ofMillis(connectionTimeout));

        return new RestTemplate(factory);
    }

    @Bean
    public OpenAPI reportServiceOpenAPI() {
        return new OpenAPI()
                .info(new Info()
                        .title("OtterWorks Report Service API")
                        .description("Legacy report generation service for PDF, CSV, and Excel exports")
                        .version("0.1.0")
                        .contact(new Contact()
                                .name("OtterWorks Engineering")
                                .email("engineering@otterworks.example.com")));
    }

    public String getAnalyticsServiceUrl() {
        return analyticsServiceUrl;
    }

    public String getAuditServiceUrl() {
        return auditServiceUrl;
    }

    public String getAuthServiceUrl() {
        return authServiceUrl;
    }

    public String getReportOutputDir() {
        return reportOutputDir;
    }

    public int getMaxRows() {
        return maxRows;
    }
}
