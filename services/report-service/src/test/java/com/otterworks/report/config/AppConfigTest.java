package com.otterworks.report.config;

import org.junit.Before;
import org.junit.Test;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

/**
 * Unit tests for {@link AppConfig}. The {@code @Value} fields are populated directly so the
 * configuration can be exercised without booting a Spring context.
 */
public class AppConfigTest {

    private AppConfig appConfig;

    @Before
    public void setUp() {
        appConfig = new AppConfig();
        ReflectionTestUtils.setField(appConfig, "analyticsServiceUrl", "http://analytics:8088");
        ReflectionTestUtils.setField(appConfig, "auditServiceUrl", "http://audit:8090");
        ReflectionTestUtils.setField(appConfig, "authServiceUrl", "http://auth:8081");
        ReflectionTestUtils.setField(appConfig, "reportOutputDir", "/tmp/reports");
        ReflectionTestUtils.setField(appConfig, "maxRows", 25000);
        ReflectionTestUtils.setField(appConfig, "connectionTimeout", 1234);
        ReflectionTestUtils.setField(appConfig, "readTimeout", 5678);
    }

    @Test
    public void exposesTheConfiguredDownstreamUrls() {
        assertEquals("http://analytics:8088", appConfig.getAnalyticsServiceUrl());
        assertEquals("http://audit:8090", appConfig.getAuditServiceUrl());
        assertEquals("http://auth:8081", appConfig.getAuthServiceUrl());
    }

    @Test
    public void exposesTheReportGenerationLimits() {
        assertEquals("/tmp/reports", appConfig.getReportOutputDir());
        assertEquals(25000, appConfig.getMaxRows());
    }

    @Test
    public void restTemplateUsesAPooledHttpComponentsRequestFactory() {
        RestTemplate restTemplate = appConfig.restTemplate();

        assertNotNull(restTemplate);
        assertTrue(restTemplate.getRequestFactory() instanceof HttpComponentsClientHttpRequestFactory);
    }
}
