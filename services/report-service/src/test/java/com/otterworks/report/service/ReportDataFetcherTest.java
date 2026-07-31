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
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link ReportDataFetcher}.
 *
 * The REST boundary is mocked, so no HTTP call leaves the JVM. Dates are fixed instants
 * because they are part of the cache key and of the request URL under assertion.
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
        // A fresh fetcher per test means a fresh Guava cache — no state leaks between tests.
        fetcher = new ReportDataFetcher(restTemplate, appConfig);
    }

    // ----- fetchAnalyticsData -----

    @Test
    public void fetchAnalyticsDataReturnsEventsFromTheAnalyticsService() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        List<Map<String, Object>> events = eventRows("evt-1", "evt-2");
        stubGetForEntity(bodyWith("events", events));

        List<Map<String, Object>> result = fetcher.fetchAnalyticsData(FROM, TO, null);

        assertEquals(events, result);
        assertEquals("http://analytics:8088/api/v1/analytics/events"
                        + "?from=2024-01-01T00:00:00Z&to=2024-02-01T00:00:00Z",
                capturedUrl());
    }

    @Test
    public void fetchAnalyticsDataAppendsTheMetricParameterWhenSupplied() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubGetForEntity(bodyWith("events", eventRows("evt-1")));

        Map<String, String> parameters = new HashMap<>();
        parameters.put("metric", "uploads");

        fetcher.fetchAnalyticsData(FROM, TO, parameters);

        assertTrue(capturedUrl().endsWith("&metric=uploads"));
    }

    @Test
    public void fetchAnalyticsDataIgnoresABlankMetricParameter() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubGetForEntity(bodyWith("events", eventRows("evt-1")));

        Map<String, String> parameters = new HashMap<>();
        parameters.put("metric", "   ");

        fetcher.fetchAnalyticsData(FROM, TO, parameters);

        assertTrue("blank metric must not reach the URL", !capturedUrl().contains("metric="));
    }

    @Test
    public void fetchAnalyticsDataCachesPerDateRangeAndMetric() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubGetForEntity(bodyWith("events", eventRows("evt-1")));

        Map<String, String> uploads = new HashMap<>();
        uploads.put("metric", "uploads");

        fetcher.fetchAnalyticsData(FROM, TO, null);
        fetcher.fetchAnalyticsData(FROM, TO, null);          // served from cache
        fetcher.fetchAnalyticsData(FROM, TO, uploads);       // different key -> refetch

        verify(restTemplate, times(2)).getForEntity(startsWith("http://analytics"), eq(Map.class));
    }

    @Test
    public void fetchAnalyticsDataReturnsEmptyListWhenTheResponseHasNoEvents() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubGetForEntity(bodyWith("unexpected", Collections.emptyList()));

        assertEquals(Collections.emptyList(), fetcher.fetchAnalyticsData(FROM, TO, null));
    }

    @Test
    public void fetchAnalyticsDataReturnsEmptyListWhenTheResponseHasNoBody() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubGetForEntity(new ResponseEntity<Map>(HttpStatus.NO_CONTENT));

        assertEquals(Collections.emptyList(), fetcher.fetchAnalyticsData(FROM, TO, null));
    }

    @Test
    public void fetchAnalyticsDataPropagatesRestFailuresWithoutCachingThem() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        RestClientException failure = new ResourceAccessException("analytics down");
        when(restTemplate.getForEntity(startsWith("http://analytics"), eq(Map.class)))
                .thenThrow(failure)
                .thenReturn(bodyWith("events", eventRows("evt-1")));

        try {
            fetcher.fetchAnalyticsData(FROM, TO, null);
            fail("expected the REST failure to surface");
        } catch (UncheckedExecutionException e) {
            assertEquals(failure, e.getCause());
        }

        // The failure was not cached: the next call hits the service again and succeeds.
        assertEquals(eventRows("evt-1"), fetcher.fetchAnalyticsData(FROM, TO, null));
        verify(restTemplate, times(2)).getForEntity(startsWith("http://analytics"), eq(Map.class));
    }

    // ----- fetchAuditData -----

    @Test
    public void fetchAuditDataReturnsEventsFromTheAuditService() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        List<Map<String, Object>> events = eventRows("aud-1");
        stubGetForEntity(bodyWith("events", events));

        assertEquals(events, fetcher.fetchAuditData(FROM, TO, null));
        assertEquals("http://audit:8090/api/v1/audit/events"
                        + "?from=2024-01-01T00:00:00Z&to=2024-02-01T00:00:00Z",
                capturedUrl());
    }

    @Test
    public void fetchAuditDataReturnsEmptyListWhenTheResponseHasNoEvents() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        stubGetForEntity(bodyWith("entries", Collections.emptyList()));

        assertEquals(Collections.emptyList(), fetcher.fetchAuditData(FROM, TO, null));
    }

    @Test
    public void fetchAuditDataIsCachedPerDateRange() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        stubGetForEntity(bodyWith("events", eventRows("aud-1")));

        fetcher.fetchAuditData(FROM, TO, null);
        fetcher.fetchAuditData(FROM, TO, null);

        verify(restTemplate, times(1)).getForEntity(startsWith("http://audit"), eq(Map.class));
    }

    @Test
    public void fetchAuditDataPropagatesRestFailures() {
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit:8090");
        RestClientException failure = new ResourceAccessException("audit down");
        when(restTemplate.getForEntity(startsWith("http://audit"), eq(Map.class))).thenThrow(failure);

        try {
            fetcher.fetchAuditData(FROM, TO, null);
            fail("expected the REST failure to surface");
        } catch (UncheckedExecutionException e) {
            assertEquals(failure, e.getCause());
        }
    }

    // ----- fetchUserActivityData -----

    @Test
    public void fetchUserActivityDataReturnsActivitiesFromTheAuthService() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        List<Map<String, Object>> activities = eventRows("user-1");
        stubGetForEntity(bodyWith("activities", activities));

        assertEquals(activities, fetcher.fetchUserActivityData(FROM, TO, null));
        assertEquals("http://auth:8081/api/v1/users/activity"
                        + "?from=2024-01-01T00:00:00Z&to=2024-02-01T00:00:00Z",
                capturedUrl());
    }

    @Test
    public void fetchUserActivityDataReturnsEmptyListWhenTheResponseHasNoActivities() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        stubGetForEntity(bodyWith("events", Collections.emptyList()));

        assertEquals(Collections.emptyList(), fetcher.fetchUserActivityData(FROM, TO, null));
    }

    @Test
    public void fetchUserActivityDataIsNotCached() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        stubGetForEntity(bodyWith("activities", eventRows("user-1")));

        fetcher.fetchUserActivityData(FROM, TO, null);
        fetcher.fetchUserActivityData(FROM, TO, null);

        verify(restTemplate, times(2)).getForEntity(startsWith("http://auth"), eq(Map.class));
    }

    @Test
    public void fetchUserActivityDataFallsBackToSampleDataWhenTheAuthServiceFails() {
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth:8081");
        when(restTemplate.getForEntity(startsWith("http://auth"), eq(Map.class)))
                .thenThrow(new ResourceAccessException("auth down"));

        List<Map<String, Object>> sample = fetcher.fetchUserActivityData(FROM, TO, null);

        assertEquals(25, sample.size());
        Map<String, Object> first = sample.get(0);
        assertEquals("user-000", first.get("user_id"));
        assertEquals("user0@otterworks.example.com", first.get("email"));
        assertEquals(10, first.get("files_uploaded"));
        assertEquals(5, first.get("docs_created"));
        assertEquals(100, first.get("storage_used_mb"));
        assertEquals(0, first.get("collaborations"));
        assertEquals(Boolean.FALSE, first.get("active")); // index 0 -> inactive
        assertNotNull(first.get("last_login"));
        assertEquals(Boolean.TRUE, sample.get(1).get("active"));
        assertEquals("user-024", sample.get(24).get("user_id"));
    }

    @Test
    public void fetchersOnlyTalkToTheirOwnDownstreamService() {
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics:8088");
        stubGetForEntity(bodyWith("events", eventRows("evt-1")));

        fetcher.fetchAnalyticsData(FROM, TO, null);

        verify(appConfig).getAnalyticsServiceUrl();
        verify(appConfig, never()).getAuditServiceUrl();
        verify(appConfig, never()).getAuthServiceUrl();
        verifyNoMoreInteractions(appConfig);
    }

    // ----- helpers -----

    @SuppressWarnings("unchecked")
    private void stubGetForEntity(ResponseEntity<Map> response) {
        when(restTemplate.getForEntity(org.mockito.ArgumentMatchers.anyString(), eq(Map.class)))
                .thenReturn(response);
    }

    @SuppressWarnings("unchecked")
    private ResponseEntity<Map> bodyWith(String key, Object value) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put(key, value);
        return new ResponseEntity<Map>(body, HttpStatus.OK);
    }

    private String capturedUrl() {
        ArgumentCaptor<String> url = ArgumentCaptor.forClass(String.class);
        verify(restTemplate, org.mockito.Mockito.atLeastOnce()).getForEntity(url.capture(), eq(Map.class));
        return url.getValue();
    }

    private static List<Map<String, Object>> eventRows(String... ids) {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (String id : Arrays.asList(ids)) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", id);
            rows.add(row);
        }
        return rows;
    }
}
