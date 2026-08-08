package com.otterworks.report.config;

import org.junit.Before;
import org.junit.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;

/**
 * Unit tests for {@link AppConfig}: the externalised service URLs and the pooled
 * {@link RestTemplate} bean, exercised without starting a Spring context.
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
        ReflectionTestUtils.setField(appConfig, "maxRows", 50_000);
        ReflectionTestUtils.setField(appConfig, "connectionTimeout", 5_000);
        ReflectionTestUtils.setField(appConfig, "readTimeout", 30_000);
    }

    @Test
    public void exposesTheConfiguredServiceUrlsAndLimits() {
        assertEquals("http://analytics:8088", appConfig.getAnalyticsServiceUrl());
        assertEquals("http://audit:8090", appConfig.getAuditServiceUrl());
        assertEquals("http://auth:8081", appConfig.getAuthServiceUrl());
        assertEquals("/tmp/reports", appConfig.getReportOutputDir());
        assertEquals(50_000, appConfig.getMaxRows());
    }

    @Test
    public void buildsARestTemplateBackedByAPooledHttpClient() {
        RestTemplate restTemplate = appConfig.restTemplate();

        assertNotNull(restTemplate);
        assertNotNull(restTemplate.getRequestFactory());
    }
}
