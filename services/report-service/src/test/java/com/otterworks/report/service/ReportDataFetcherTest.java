package com.otterworks.report.service;

import com.google.common.util.concurrent.UncheckedExecutionException;
import com.otterworks.report.config.AppConfig;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.ResourceAccessException;
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
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportDataFetcher}.
 *
 * The HTTP boundary is mocked, so no network, no clock dependence and no cache leakage
 * between tests (a fresh fetcher — and therefore a fresh Guava cache — per test).
 */
@RunWith(MockitoJUnitRunner.class)
public class ReportDataFetcherTest {

    private static final Date FROM = new Date(1_704_067_200_000L); // 2024-01-01T00:00:00Z
    private static final Date TO = new Date(1_706_745_600_000L);   // 2024-02-01T00:00:00Z

    @Mock
    private RestTemplate restTemplate;

    @Mock
    private AppConfig appConfig;

    private ReportDataFetcher fetcher;

    @Before
    public void setUp() {
        fetcher = new ReportDataFetcher(restTemplate, appConfig);
    }

    @Test
    public void fetchAnalyticsDataReturnsTheEventsFromTheAnalyticsService() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubResponse(body("events", Arrays.asList(row("evt-1"), row("evt-2"))));

        List<Map<String, Object>> result = fetcher.fetchAnalyticsData(FROM, TO, null);

        assertEquals(2, result.size());
        assertEquals("evt-1", result.get(0).get("event_id"));
        assertEquals("http://analytics:8088/api/v1/analytics/events"
                + "?from=2024-01-01T00:00:00Z&to=2024-02-01T00:00:00Z", capturedUrl());
    }

    @Test
    public void fetchAnalyticsDataAppendsTheMetricParameterWhenPresent() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubResponse(body("events", Collections.singletonList(row("evt-1"))));

        Map<String, String> params = new HashMap<String, String>();
        params.put("metric", "uploads");
        fetcher.fetchAnalyticsData(FROM, TO, params);

        assertTrue(capturedUrl(), capturedUrl().endsWith("&metric=uploads"));
    }

    @Test
    public void fetchAnalyticsDataIgnoresABlankMetricParameter() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubResponse(body("events", Collections.<Map<String, Object>>emptyList()));

        Map<String, String> params = new HashMap<String, String>();
        params.put("metric", "   ");
        fetcher.fetchAnalyticsData(FROM, TO, params);

        assertFalse(capturedUrl(), capturedUrl().contains("metric="));
    }

    @Test
    public void fetchAnalyticsDataCachesSuccessfulResponsesPerDateRangeAndMetric() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubResponse(body("events", Collections.singletonList(row("evt-1"))));

        fetcher.fetchAnalyticsData(FROM, TO, null);
        fetcher.fetchAnalyticsData(FROM, TO, null);

        verify(restTemplate, times(1)).getForEntity(anyString(), eq(Map.class));
    }

    @Test
    public void fetchAnalyticsDataReturnsEmptyWhenThePayloadHasNoEventsKey() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubResponse(body("unexpected", "payload"));

        assertTrue(fetcher.fetchAnalyticsData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchAnalyticsDataReturnsEmptyWhenTheResponseHasNoBody() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(new ResponseEntity<Map>(HttpStatus.NO_CONTENT));

        assertTrue(fetcher.fetchAnalyticsData(FROM, TO, null).isEmpty());
    }

    /**
     * A transport failure is deliberately not cached. Guava wraps the unchecked
     * {@code RestClientException} in an {@code UncheckedExecutionException}, which is not the
     * {@code ExecutionException} the fallback catch-block handles, so the failure propagates to
     * the caller instead of yielding sample data. See the note in the PR body.
     */
    @Test
    public void fetchAnalyticsDataPropagatesTransportFailures() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new ResourceAccessException("connection refused"));

        try {
            fetcher.fetchAnalyticsData(FROM, TO, null);
            fail("expected the transport failure to propagate");
        } catch (UncheckedExecutionException e) {
            assertTrue(e.getCause() instanceof ResourceAccessException);
        }
    }

    @Test
    public void fetchAuditDataReturnsTheEventsFromTheAuditService() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        stubResponse(body("events", Collections.singletonList(row("aud-1"))));

        List<Map<String, Object>> result = fetcher.fetchAuditData(FROM, TO, null);

        assertEquals(1, result.size());
        assertEquals("http://audit:8090/api/v1/audit/events"
                + "?from=2024-01-01T00:00:00Z&to=2024-02-01T00:00:00Z", capturedUrl());
    }

    @Test
    public void fetchAuditDataReturnsEmptyWhenThePayloadHasNoEventsKey() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        stubResponse(body("total", 0));

        assertTrue(fetcher.fetchAuditData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchAuditDataCachesSuccessfulResponses() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        stubResponse(body("events", Collections.singletonList(row("aud-1"))));

        fetcher.fetchAuditData(FROM, TO, null);
        fetcher.fetchAuditData(FROM, TO, null);

        verify(restTemplate, times(1)).getForEntity(anyString(), eq(Map.class));
    }

    @Test
    public void fetchUserActivityDataReturnsTheActivitiesFromTheAuthService() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        stubResponse(body("activities", Collections.singletonList(row("user-1"))));

        List<Map<String, Object>> result = fetcher.fetchUserActivityData(FROM, TO, null);

        assertEquals(1, result.size());
        assertEquals("http://auth:8081/api/v1/users/activity"
                + "?from=2024-01-01T00:00:00Z&to=2024-02-01T00:00:00Z", capturedUrl());
    }

    @Test
    public void fetchUserActivityDataReturnsEmptyWhenThePayloadHasNoActivitiesKey() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        stubResponse(body("events", Collections.emptyList()));

        assertTrue(fetcher.fetchUserActivityData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchUserActivityDataReturnsEmptyWhenTheResponseHasNoBody() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(new ResponseEntity<Map>(HttpStatus.NO_CONTENT));

        assertTrue(fetcher.fetchUserActivityData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchUserActivityDataFallsBackToSampleDataWhenTheAuthServiceIsUnreachable() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new ResourceAccessException("connection refused"));

        List<Map<String, Object>> result = fetcher.fetchUserActivityData(FROM, TO, null);

        assertEquals(25, result.size());
        Map<String, Object> first = result.get(0);
        assertEquals("user-000", first.get("user_id"));
        assertEquals("user0@otterworks.example.com", first.get("email"));
        assertEquals(Integer.valueOf(10), first.get("files_uploaded"));
        assertEquals(Integer.valueOf(5), first.get("docs_created"));
        assertEquals(Integer.valueOf(100), first.get("storage_used_mb"));
        assertEquals(Integer.valueOf(0), first.get("collaborations"));
        assertEquals(Boolean.FALSE, first.get("active"));
        assertEquals(Boolean.TRUE, result.get(1).get("active"));
    }

    @Test
    public void analyticsAndAuditResultsAreCachedUnderDistinctKeys() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        stubResponse(body("events", Collections.singletonList(row("evt-1"))));

        fetcher.fetchAnalyticsData(FROM, TO, null);
        fetcher.fetchAuditData(FROM, TO, null);

        verify(restTemplate, times(2)).getForEntity(anyString(), eq(Map.class));
    }

    // ----- helpers -----

    @SuppressWarnings("unchecked")
    private void stubResponse(Map<String, Object> responseBody) {
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(new ResponseEntity<Map>(responseBody, HttpStatus.OK));
    }

    private String capturedUrl() {
        ArgumentCaptor<String> url = ArgumentCaptor.forClass(String.class);
        verify(restTemplate).getForEntity(url.capture(), eq(Map.class));
        return url.getValue();
    }

    private static Map<String, Object> body(String key, Object value) {
        Map<String, Object> body = new HashMap<String, Object>();
        body.put(key, value);
        return body;
    }

    private static Map<String, Object> row(String id) {
        Map<String, Object> row = new HashMap<String, Object>();
        row.put("event_id", id);
        row.put("user_id", id);
        return row;
    }
}
