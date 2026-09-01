package com.otterworks.report.config;

import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

/**
 * Application configuration — wires up RestTemplate and external service URLs.
 *
 * LEGACY PATTERNS:
 * - Uses RestTemplate (deprecated in Spring 5.x, removed path in 6.x)
 * - Uses Apache HttpComponents 4.x directly
 * - Manual connection pool management instead of reactive WebClient
 *
 * UPGRADE NOTES:
 * - Replace RestTemplate with WebClient (reactive) or RestClient (Spring 6.1+)
 * - Replace Apache HttpComponents with Reactor Netty or JDK HttpClient
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

    // LEGACY: RestTemplate with Apache HttpComponents 4.x connection pool
    @Bean
    public RestTemplate restTemplate() {
        PoolingHttpClientConnectionManager connectionManager = new PoolingHttpClientConnectionManager();
        connectionManager.setMaxTotal(50);
        connectionManager.setDefaultMaxPerRoute(20);

        CloseableHttpClient httpClient = HttpClients.custom()
                .setConnectionManager(connectionManager)
                .build();

        HttpComponentsClientHttpRequestFactory factory = new HttpComponentsClientHttpRequestFactory(httpClient);
        factory.setConnectTimeout(connectionTimeout);
        // Manual migration to `SocketConfig.Builder.setSoTimeout(Timeout)` necessary; see: https://docs.spring.io/spring-framework/docs/6.0.0/javadoc-api/org/springframework/http/client/HttpComponentsClientHttpRequestFactory.html#setReadTimeout(int)
        factory.setReadTimeout(readTimeout);

        return new RestTemplate(factory);
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
