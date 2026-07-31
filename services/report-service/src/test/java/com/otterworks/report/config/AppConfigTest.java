package com.otterworks.report.config;

import org.apache.http.client.config.RequestConfig;
import org.apache.http.impl.client.CloseableHttpClient;
import org.junit.Before;
import org.junit.Test;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNotSame;
import static org.junit.Assert.assertTrue;

/**
 * Unit tests for {@link AppConfig}.
 *
 * The @Value-injected fields are set directly, so the wiring of the RestTemplate (pooled
 * Apache HttpComponents factory + configured timeouts) can be asserted without booting Spring.
 */
public class AppConfigTest {

    private AppConfig appConfig;

    @Before
    public void setUp() {
        appConfig = new AppConfig();
        ReflectionTestUtils.setField(appConfig, "analyticsServiceUrl", "http://analytics:8088");
        ReflectionTestUtils.setField(appConfig, "auditServiceUrl", "http://audit:8090");
        ReflectionTestUtils.setField(appConfig, "authServiceUrl", "http://auth:8081");
        ReflectionTestUtils.setField(appConfig, "reportOutputDir", "/var/reports");
        ReflectionTestUtils.setField(appConfig, "maxRows", 1234);
        ReflectionTestUtils.setField(appConfig, "connectionTimeout", 4321);
        ReflectionTestUtils.setField(appConfig, "readTimeout", 9876);
    }

    @Test
    public void exposesTheConfiguredDownstreamUrlsAndLimits() {
        assertEquals("http://analytics:8088", appConfig.getAnalyticsServiceUrl());
        assertEquals("http://audit:8090", appConfig.getAuditServiceUrl());
        assertEquals("http://auth:8081", appConfig.getAuthServiceUrl());
        assertEquals("/var/reports", appConfig.getReportOutputDir());
        assertEquals(1234, appConfig.getMaxRows());
    }

    @Test
    public void restTemplateUsesAPooledHttpComponentsFactoryWithTheConfiguredTimeouts() {
        RestTemplate restTemplate = appConfig.restTemplate();

        assertNotNull(restTemplate);
        assertTrue("expected an Apache HttpComponents backed factory but was "
                        + restTemplate.getRequestFactory().getClass(),
                restTemplate.getRequestFactory() instanceof HttpComponentsClientHttpRequestFactory);

        HttpComponentsClientHttpRequestFactory factory =
                (HttpComponentsClientHttpRequestFactory) restTemplate.getRequestFactory();
        assertTrue(factory.getHttpClient() instanceof CloseableHttpClient);

        RequestConfig requestConfig = (RequestConfig) ReflectionTestUtils.getField(factory, "requestConfig");
        assertNotNull(requestConfig);
        assertEquals(4321, requestConfig.getConnectTimeout());
        assertEquals(9876, requestConfig.getSocketTimeout());
    }

    @Test
    public void eachRestTemplateGetsItsOwnConnectionPool() {
        assertNotSame(appConfig.restTemplate().getRequestFactory(),
                appConfig.restTemplate().getRequestFactory());
    }
}
