package com.otterworks.report.service;

import com.google.common.util.concurrent.UncheckedExecutionException;
import com.otterworks.report.config.AppConfig;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportDataFetcher}.
 *
 * The RestTemplate boundary is mocked, so no HTTP traffic leaves the JVM. Dates are fixed
 * instants and every URL assertion is made in UTC.
 */
public class ReportDataFetcherTest {

    /** 2024-01-01T00:00:00Z */
    private static final Date FROM = new Date(1_704_067_200_000L);

    /** 2024-01-08T00:00:00Z */
    private static final Date TO = new Date(1_704_672_000_000L);

    private static final String FROM_ISO = "2024-01-01T00:00:00Z";
    private static final String TO_ISO = "2024-01-08T00:00:00Z";

    @Mock
    private RestTemplate restTemplate;

    @Mock
    private AppConfig appConfig;

    private AutoCloseable mocks;
    private ReportDataFetcher fetcher;

    @Before
    public void setUp() {
        mocks = MockitoAnnotations.openMocks(this);
        // A fresh fetcher per test means a fresh Guava cache, so tests cannot leak into each other.
        fetcher = new ReportDataFetcher(restTemplate, appConfig);
    }

    @After
    public void tearDown() throws Exception {
        mocks.close();
    }

    // ----- fetchAnalyticsData -----

    @Test
    public void fetchAnalyticsDataReturnsEventsFromTheResponseBody() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubEvents("events", row("event_id", "evt-1"));

        List<Map<String, Object>> result = fetcher.fetchAnalyticsData(FROM, TO, null);

        assertEquals(1, result.size());
        assertEquals("evt-1", result.get(0).get("event_id"));
        assertEquals("http://analytics:8088/api/v1/analytics/events?from=" + FROM_ISO + "&to=" + TO_ISO,
                capturedUrl());
    }

    @Test
    public void fetchAnalyticsDataAppendsTheMetricParameterWhenPresent() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubEvents("events");

        Map<String, String> params = new HashMap<>();
        params.put("metric", "downloads");
        fetcher.fetchAnalyticsData(FROM, TO, params);

        assertTrue(capturedUrl().endsWith("&metric=downloads"));
    }

    @Test
    public void fetchAnalyticsDataIgnoresABlankMetricParameter() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubEvents("events");

        Map<String, String> params = new HashMap<>();
        params.put("metric", "   ");
        fetcher.fetchAnalyticsData(FROM, TO, params);

        assertFalse(capturedUrl().contains("metric="));
    }

    @Test
    public void fetchAnalyticsDataReturnsEmptyWhenTheBodyHasNoEventsKey() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubEvents("something-else");

        assertTrue(fetcher.fetchAnalyticsData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchAnalyticsDataReturnsEmptyWhenTheBodyIsNull() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(new ResponseEntity<Map>(HttpStatus.NO_CONTENT));

        assertTrue(fetcher.fetchAnalyticsData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchAnalyticsDataCachesSuccessfulResponsesPerDateRangeAndMetric() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubEvents("events", row("event_id", "evt-1"));

        fetcher.fetchAnalyticsData(FROM, TO, null);
        fetcher.fetchAnalyticsData(FROM, TO, null);

        verify(restTemplate, times(1)).getForEntity(anyString(), eq(Map.class));
    }

    @Test
    public void fetchAnalyticsDataDoesNotShareCacheEntriesAcrossMetrics() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubEvents("events", row("event_id", "evt-1"));

        Map<String, String> params = new HashMap<>();
        params.put("metric", "uploads");
        fetcher.fetchAnalyticsData(FROM, TO, null);
        fetcher.fetchAnalyticsData(FROM, TO, params);

        verify(restTemplate, times(2)).getForEntity(anyString(), eq(Map.class));
    }

    /**
     * Documents current behaviour, which looks like a defect in the golden app.
     *
     * The loader lets {@link RestClientException} (unchecked) escape, and Guava wraps unchecked
     * loader failures in {@link UncheckedExecutionException} — not {@link
     * java.util.concurrent.ExecutionException}. The `catch (ExecutionException)` fallback to
     * sample data in {@code fetchAnalyticsData} therefore never runs for a transport failure,
     * and the exception propagates to the caller instead. Reported, not fixed: production code
     * is out of scope for this change.
     */
    @Test
    public void fetchAnalyticsDataPropagatesTransportFailuresInsteadOfFallingBackToSampleData() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new RestClientException("analytics unreachable"));

        try {
            fetcher.fetchAnalyticsData(FROM, TO, null);
            fail("expected the Guava-wrapped transport failure to propagate");
        } catch (UncheckedExecutionException e) {
            assertTrue(e.getCause() instanceof RestClientException);
        }
    }

    @Test
    public void fetchAnalyticsDataDoesNotCacheFailedResponses() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new RestClientException("analytics unreachable"));

        for (int i = 0; i < 2; i++) {
            try {
                fetcher.fetchAnalyticsData(FROM, TO, null);
                fail("expected the transport failure to propagate");
            } catch (UncheckedExecutionException expected) {
                // each attempt must reach the backend again
            }
        }

        verify(restTemplate, times(2)).getForEntity(anyString(), eq(Map.class));
    }

    // ----- fetchAuditData -----

    @Test
    public void fetchAuditDataReturnsEventsFromTheResponseBody() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        stubEvents("events", row("audit_id", "aud-1"));

        List<Map<String, Object>> result = fetcher.fetchAuditData(FROM, TO, null);

        assertEquals(1, result.size());
        assertEquals("aud-1", result.get(0).get("audit_id"));
        assertEquals("http://audit:8090/api/v1/audit/events?from=" + FROM_ISO + "&to=" + TO_ISO,
                capturedUrl());
    }

    @Test
    public void fetchAuditDataReturnsEmptyWhenTheBodyHasNoEventsKey() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        stubEvents("entries");

        assertTrue(fetcher.fetchAuditData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchAuditDataCachesSuccessfulResponses() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        stubEvents("events", row("audit_id", "aud-1"));

        fetcher.fetchAuditData(FROM, TO, null);
        fetcher.fetchAuditData(FROM, TO, null);

        verify(restTemplate, times(1)).getForEntity(anyString(), eq(Map.class));
    }

    /** Same defect as the analytics path — see the note on the analytics test. */
    @Test
    public void fetchAuditDataPropagatesTransportFailuresInsteadOfFallingBackToSampleData() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new RestClientException("audit unreachable"));

        try {
            fetcher.fetchAuditData(FROM, TO, null);
            fail("expected the Guava-wrapped transport failure to propagate");
        } catch (UncheckedExecutionException e) {
            assertTrue(e.getCause() instanceof RestClientException);
        }
    }

    // ----- fetchUserActivityData -----

    @Test
    public void fetchUserActivityDataReturnsActivitiesFromTheResponseBody() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        stubEvents("activities", row("user_id", "user-1"));

        List<Map<String, Object>> result = fetcher.fetchUserActivityData(FROM, TO, null);

        assertEquals(1, result.size());
        assertEquals("user-1", result.get(0).get("user_id"));
        assertEquals("http://auth:8081/api/v1/users/activity?from=" + FROM_ISO + "&to=" + TO_ISO,
                capturedUrl());
    }

    @Test
    public void fetchUserActivityDataReturnsEmptyWhenTheBodyHasNoActivitiesKey() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        stubEvents("events");

        assertTrue(fetcher.fetchUserActivityData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchUserActivityDataReturnsEmptyWhenTheBodyIsNull() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(new ResponseEntity<Map>(HttpStatus.NO_CONTENT));

        assertTrue(fetcher.fetchUserActivityData(FROM, TO, null).isEmpty());
    }

    /**
     * Unlike the two cached paths, this one catches {@link RestClientException} directly, so the
     * sample-data fallback is actually reachable here.
     */
    @Test
    public void fetchUserActivityDataFallsBackToSampleDataOnTransportFailure() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new RestClientException("auth unreachable"));

        List<Map<String, Object>> result = fetcher.fetchUserActivityData(FROM, TO, null);

        assertEquals(25, result.size());
        Map<String, Object> first = result.get(0);
        assertEquals("user-000", first.get("user_id"));
        assertEquals("user0@otterworks.example.com", first.get("email"));
        assertEquals(10, first.get("files_uploaded"));
        assertEquals(Boolean.FALSE, first.get("active"));
        assertEquals(Boolean.TRUE, result.get(1).get("active"));
    }

    @Test
    public void fetchUserActivityDataIsNotCached() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        stubEvents("activities", row("user_id", "user-1"));

        fetcher.fetchUserActivityData(FROM, TO, null);
        fetcher.fetchUserActivityData(FROM, TO, null);

        verify(restTemplate, times(2)).getForEntity(anyString(), eq(Map.class));
        verifyNoMoreInteractions(restTemplate);
    }

    // ----- helpers -----

    @SafeVarargs
    private final void stubEvents(String bodyKey, Map<String, Object>... rows) {
        Map<String, Object> body = new HashMap<>();
        body.put(bodyKey, Arrays.asList(rows));
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(new ResponseEntity<Map>(body, HttpStatus.OK));
    }

    private String capturedUrl() {
        ArgumentCaptor<String> url = ArgumentCaptor.forClass(String.class);
        verify(restTemplate, org.mockito.Mockito.atLeastOnce()).getForEntity(url.capture(), eq(Map.class));
        return url.getValue();
    }

    private static Map<String, Object> row(String key, Object value) {
        return Collections.<String, Object>singletonMap(key, value);
    }
}
