package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import org.junit.Before;
import org.junit.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportDataFetcher} failure handling: upstream failures must surface as
 * {@link ReportDataFetchException} unless the standalone/demo sample-data fallback is enabled.
 */
public class ReportDataFetcherTest {

    private static final String ANALYTICS_URL = "http://analytics-test";
    private static final String AUDIT_URL = "http://audit-test";
    private static final String AUTH_URL = "http://auth-test";

    private RestTemplate restTemplate;
    private AppConfig appConfig;
    private ReportDataFetcher fetcher;
    private Date from;
    private Date to;

    @Before
    public void setUp() {
        restTemplate = mock(RestTemplate.class);
        appConfig = mock(AppConfig.class);
        when(appConfig.getAnalyticsServiceUrl()).thenReturn(ANALYTICS_URL);
        when(appConfig.getAuditServiceUrl()).thenReturn(AUDIT_URL);
        when(appConfig.getAuthServiceUrl()).thenReturn(AUTH_URL);
        when(appConfig.isSampleDataFallbackEnabled()).thenReturn(false);
        fetcher = new ReportDataFetcher(restTemplate, appConfig);
        to = new Date();
        from = new Date(to.getTime() - 86400000L);
    }

    @Test
    public void analyticsFailurePropagatesUnwrappedCause() {
        ResourceAccessException upstream = new ResourceAccessException("Connection refused");
        when(restTemplate.getForEntity(startsWith(ANALYTICS_URL), eq(Map.class))).thenThrow(upstream);

        ReportDataFetchException e = expectFetchFailure(() -> fetcher.fetchAnalyticsData(from, to, null));

        assertSame(upstream, e.getCause());
        assertEquals("Failed to fetch analytics data from analytics-service", e.getMessage());
    }

    @Test
    public void auditFailurePropagatesUnwrappedCause() {
        HttpServerErrorException upstream = new HttpServerErrorException(HttpStatus.SERVICE_UNAVAILABLE);
        when(restTemplate.getForEntity(startsWith(AUDIT_URL), eq(Map.class))).thenThrow(upstream);

        ReportDataFetchException e = expectFetchFailure(() -> fetcher.fetchAuditData(from, to, null));

        assertSame(upstream, e.getCause());
        assertEquals("Failed to fetch audit data from audit-service", e.getMessage());
    }

    @Test
    public void userActivityFailurePropagatesInsteadOfReturningSampleData() {
        HttpServerErrorException upstream = new HttpServerErrorException(HttpStatus.BAD_GATEWAY);
        when(restTemplate.getForEntity(startsWith(AUTH_URL), eq(Map.class))).thenThrow(upstream);

        ReportDataFetchException e = expectFetchFailure(() -> fetcher.fetchUserActivityData(from, to, null));

        assertSame(upstream, e.getCause());
        assertEquals("Failed to fetch user activity data from auth-service", e.getMessage());
    }

    @Test
    public void errorMessageDoesNotLeakUpstreamUrl() {
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new ResourceAccessException("I/O error on GET request for \"" + AUTH_URL + "/x\""));

        ReportDataFetchException e = expectFetchFailure(() -> fetcher.fetchUserActivityData(from, to, null));

        assertFalse(e.getMessage().contains(AUTH_URL));
    }

    @Test
    public void failedAnalyticsFetchIsNotCached() {
        when(restTemplate.getForEntity(startsWith(ANALYTICS_URL), eq(Map.class)))
                .thenThrow(new ResourceAccessException("down"))
                .thenReturn(ResponseEntity.ok(body("events", 3)));

        expectFetchFailure(() -> fetcher.fetchAnalyticsData(from, to, null));

        assertEquals(3, fetcher.fetchAnalyticsData(from, to, null).size());
    }

    @Test
    public void successfulFetchesReturnUpstreamRows() {
        when(restTemplate.getForEntity(startsWith(ANALYTICS_URL), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("events", 2)));
        when(restTemplate.getForEntity(startsWith(AUDIT_URL), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("events", 4)));
        when(restTemplate.getForEntity(startsWith(AUTH_URL), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("activities", 1)));

        assertEquals(2, fetcher.fetchAnalyticsData(from, to, null).size());
        assertEquals(4, fetcher.fetchAuditData(from, to, null).size());
        assertEquals(1, fetcher.fetchUserActivityData(from, to, null).size());
    }

    @Test
    public void sampleDataReturnedOnlyWhenFallbackFlagEnabled() {
        when(appConfig.isSampleDataFallbackEnabled()).thenReturn(true);
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new ResourceAccessException("down"));

        assertEquals(50, fetcher.fetchAnalyticsData(from, to, null).size());
        assertEquals(50, fetcher.fetchAuditData(from, to, null).size());
        List<Map<String, Object>> activity = fetcher.fetchUserActivityData(from, to, null);
        assertEquals(25, activity.size());
        assertTrue(String.valueOf(activity.get(0).get("user_id")).startsWith("user-"));
    }

    private interface Fetch {
        List<Map<String, Object>> run();
    }

    private static ReportDataFetchException expectFetchFailure(Fetch fetch) {
        try {
            fetch.run();
        } catch (ReportDataFetchException e) {
            return e;
        } catch (RestClientException e) {
            fail("Expected ReportDataFetchException but RestClientException leaked: " + e);
        }
        fail("Expected ReportDataFetchException but fetch returned data");
        return null;
    }

    private static Map<String, Object> body(String key, int rows) {
        Map<String, Object> body = new HashMap<>();
        body.put(key, Collections.nCopies(rows, Collections.singletonMap("id", "row")));
        return body;
    }
}
