package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.MockitoJUnitRunner;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
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
 * The RestTemplate is mocked at the HTTP boundary, so no network, clock or file
 * system is touched. A fresh fetcher (and therefore a fresh Guava cache) is built
 * for every test.
 *
 * Written in JUnit 4 style to match the current stack.
 */
@RunWith(MockitoJUnitRunner.class)
@SuppressWarnings({"unchecked", "rawtypes"})
public class ReportDataFetcherTest {

    private static final Date FROM = new Date(1704067200000L); // 2024-01-01T00:00:00Z
    private static final Date TO = new Date(1704153600000L);   // 2024-01-02T00:00:00Z

    @Mock
    private RestTemplate restTemplate;

    @Mock
    private AppConfig appConfig;

    private ReportDataFetcher fetcher;

    @Before
    public void setUp() {
        fetcher = new ReportDataFetcher(restTemplate, appConfig);
    }

    private static Map<String, Object> body(String key, List<Map<String, Object>> rows) {
        Map<String, Object> body = new HashMap<>();
        body.put(key, rows);
        return body;
    }

    private static List<Map<String, Object>> rows(String idValue) {
        List<Map<String, Object>> rows = new ArrayList<>();
        Map<String, Object> row = new HashMap<>();
        row.put("id", idValue);
        rows.add(row);
        return rows;
    }

    // ----- analytics -----

    @Test
    public void fetchAnalyticsDataReturnsEventsAndBuildsRangeUrl() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("events", rows("evt-1"))));

        List<Map<String, Object>> result = fetcher.fetchAnalyticsData(FROM, TO, null);

        assertEquals(1, result.size());
        assertEquals("evt-1", result.get(0).get("id"));

        ArgumentCaptor<String> url = ArgumentCaptor.forClass(String.class);
        verify(restTemplate).getForEntity(url.capture(), eq(Map.class));
        assertEquals("http://analytics:8088/api/v1/analytics/events"
                + "?from=2024-01-01T00:00:00Z&to=2024-01-02T00:00:00Z", url.getValue());
    }

    @Test
    public void fetchAnalyticsDataAppendsMetricParameterWhenPresent() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("events", rows("evt-2"))));

        Map<String, String> params = new HashMap<>();
        params.put("metric", "uploads");

        List<Map<String, Object>> result = fetcher.fetchAnalyticsData(FROM, TO, params);

        assertEquals(1, result.size());
        ArgumentCaptor<String> url = ArgumentCaptor.forClass(String.class);
        verify(restTemplate).getForEntity(url.capture(), eq(Map.class));
        assertTrue(url.getValue().endsWith("&metric=uploads"));
    }

    @Test
    public void fetchAnalyticsDataIgnoresBlankMetricParameter() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("events", rows("evt-3"))));

        Map<String, String> params = new HashMap<>();
        params.put("metric", "  ");

        fetcher.fetchAnalyticsData(FROM, TO, params);

        ArgumentCaptor<String> url = ArgumentCaptor.forClass(String.class);
        verify(restTemplate).getForEntity(url.capture(), eq(Map.class));
        assertFalse(url.getValue().contains("&metric="));
    }

    @Test
    public void fetchAnalyticsDataReturnsEmptyListWhenBodyHasNoEventsKey() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(new HashMap<String, Object>()));

        assertTrue(fetcher.fetchAnalyticsData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchAnalyticsDataReturnsEmptyListWhenBodyIsNull() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok().build());

        assertTrue(fetcher.fetchAnalyticsData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchAnalyticsDataCachesSuccessfulResponsesPerDateRange() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("events", rows("evt-4"))));

        List<Map<String, Object>> first = fetcher.fetchAnalyticsData(FROM, TO, null);
        List<Map<String, Object>> second = fetcher.fetchAnalyticsData(FROM, TO, null);

        assertEquals(first, second);
        verify(restTemplate, times(1)).getForEntity(anyString(), eq(Map.class));
    }

    @Test
    public void fetchAnalyticsDataUsesDistinctCacheEntriesPerMetric() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("events", rows("evt-5"))));

        Map<String, String> params = new HashMap<>();
        params.put("metric", "downloads");

        fetcher.fetchAnalyticsData(FROM, TO, null);
        fetcher.fetchAnalyticsData(FROM, TO, params);

        verify(restTemplate, times(2)).getForEntity(anyString(), eq(Map.class));
    }

    @Test
    public void fetchAnalyticsDataPropagatesTransportFailuresWithoutCachingThem() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new RestClientException("connection refused"))
                .thenReturn(ResponseEntity.ok(body("events", rows("evt-6"))));

        try {
            fetcher.fetchAnalyticsData(FROM, TO, null);
            fail("expected the transport failure to propagate");
        } catch (RuntimeException e) {
            assertTrue(rootCause(e) instanceof RestClientException);
        }

        // The failure must not have been cached: a retry hits the service again.
        assertEquals(1, fetcher.fetchAnalyticsData(FROM, TO, null).size());
        verify(restTemplate, times(2)).getForEntity(anyString(), eq(Map.class));
    }

    // ----- audit -----

    @Test
    public void fetchAuditDataReturnsEventsAndBuildsRangeUrl() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("events", rows("aud-1"))));

        List<Map<String, Object>> result = fetcher.fetchAuditData(FROM, TO, null);

        assertEquals("aud-1", result.get(0).get("id"));
        ArgumentCaptor<String> url = ArgumentCaptor.forClass(String.class);
        verify(restTemplate).getForEntity(url.capture(), eq(Map.class));
        assertEquals("http://audit:8090/api/v1/audit/events"
                + "?from=2024-01-01T00:00:00Z&to=2024-01-02T00:00:00Z", url.getValue());
    }

    @Test
    public void fetchAuditDataReturnsEmptyListWhenBodyHasNoEventsKey() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(new HashMap<String, Object>()));

        assertTrue(fetcher.fetchAuditData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchAuditDataCachesSuccessfulResponses() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("events", rows("aud-2"))));

        fetcher.fetchAuditData(FROM, TO, null);
        fetcher.fetchAuditData(FROM, TO, null);

        verify(restTemplate, times(1)).getForEntity(anyString(), eq(Map.class));
    }

    @Test
    public void fetchAuditDataPropagatesTransportFailures() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new RestClientException("audit down"));

        try {
            fetcher.fetchAuditData(FROM, TO, null);
            fail("expected the transport failure to propagate");
        } catch (RuntimeException e) {
            assertTrue(rootCause(e) instanceof RestClientException);
        }
    }

    // ----- user activity -----

    @Test
    public void fetchUserActivityDataReturnsActivities() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("activities", rows("user-1"))));

        List<Map<String, Object>> result = fetcher.fetchUserActivityData(FROM, TO, null);

        assertEquals("user-1", result.get(0).get("id"));
        ArgumentCaptor<String> url = ArgumentCaptor.forClass(String.class);
        verify(restTemplate).getForEntity(url.capture(), eq(Map.class));
        assertEquals("http://auth:8081/api/v1/users/activity"
                + "?from=2024-01-01T00:00:00Z&to=2024-01-02T00:00:00Z", url.getValue());
    }

    @Test
    public void fetchUserActivityDataReturnsEmptyListWhenActivitiesKeyIsAbsent() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(new HashMap<String, Object>()));

        assertTrue(fetcher.fetchUserActivityData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchUserActivityDataReturnsEmptyListWhenBodyIsNull() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok().build());

        assertTrue(fetcher.fetchUserActivityData(FROM, TO, null).isEmpty());
    }

    @Test
    public void fetchUserActivityDataFallsBackToSampleDataWhenAuthServiceIsUnreachable() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new RestClientException("auth down"));

        List<Map<String, Object>> result = fetcher.fetchUserActivityData(FROM, TO, null);

        assertEquals(25, result.size());
        Map<String, Object> first = result.get(0);
        assertEquals("user-000", first.get("user_id"));
        assertEquals("user0@otterworks.example.com", first.get("email"));
        assertEquals(10, first.get("files_uploaded"));
        assertEquals(Boolean.FALSE, first.get("active"));
        assertEquals(Boolean.TRUE, result.get(1).get("active"));
        assertNotNull(first.get("last_login"));

        // The fallback is generated locally — no further HTTP calls.
        verify(restTemplate).getForEntity(anyString(), eq(Map.class));
        verifyNoMoreInteractions(restTemplate);
    }

    @Test
    public void fetchAnalyticsDataHandlesNullParametersMapWithoutMetric() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok(body("events", Collections.<Map<String, Object>>emptyList())));

        assertTrue(fetcher.fetchAnalyticsData(FROM, TO, null).isEmpty());
    }

    private static Throwable rootCause(Throwable t) {
        Throwable current = t;
        while (current.getCause() != null) {
            current = current.getCause();
        }
        return current;
    }
}
