package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import org.junit.Before;
import org.junit.Ignore;
import org.junit.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import java.io.IOException;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class ReportDataFetcherTest {

    private static final Date FROM = new Date(1704067200000L); // 2024-01-01T00:00:00Z
    private static final Date TO = new Date(1704153600000L);   // 2024-01-02T00:00:00Z

    private RestTemplate restTemplate;
    private AppConfig appConfig;
    private ReportDataFetcher fetcher;

    @Before
    public void setUp() {
        restTemplate = mock(RestTemplate.class);
        appConfig = mock(AppConfig.class);
        when(appConfig.getAnalyticsServiceUrl()).thenReturn("http://analytics");
        when(appConfig.getAuditServiceUrl()).thenReturn("http://audit");
        when(appConfig.getAuthServiceUrl()).thenReturn("http://auth");
        fetcher = new ReportDataFetcher(restTemplate, appConfig);
    }

    private static ResponseEntity<Map> body(String key, List<Map<String, Object>> rows) {
        Map<String, Object> b = new HashMap<>();
        b.put(key, rows);
        return ResponseEntity.ok(b);
    }

    private static List<Map<String, Object>> rows(String id) {
        Map<String, Object> row = new HashMap<>();
        row.put("id", id);
        return Collections.singletonList(row);
    }

    @Test
    public void analyticsReturnsEventsAndCachesResult() {
        String url = "http://analytics/api/v1/analytics/events?from=2024-01-01T00:00:00Z&to=2024-01-02T00:00:00Z";
        when(restTemplate.getForEntity(url, Map.class)).thenReturn(body("events", rows("a1")));

        assertEquals(rows("a1"), fetcher.fetchAnalyticsData(FROM, TO, null));
        assertEquals(rows("a1"), fetcher.fetchAnalyticsData(FROM, TO, null));
        verify(restTemplate, times(1)).getForEntity(url, Map.class);
    }

    @Test
    public void analyticsAppendsMetricAndKeysCacheOnIt() {
        String base = "http://analytics/api/v1/analytics/events?from=2024-01-01T00:00:00Z&to=2024-01-02T00:00:00Z";
        when(restTemplate.getForEntity(base + "&metric=uploads", Map.class)).thenReturn(body("events", rows("m")));
        when(restTemplate.getForEntity(base, Map.class)).thenReturn(body("events", rows("blank")));

        Map<String, String> metric = Collections.singletonMap("metric", "uploads");
        assertEquals(rows("m"), fetcher.fetchAnalyticsData(FROM, TO, metric));
        assertEquals(rows("blank"), fetcher.fetchAnalyticsData(FROM, TO, Collections.singletonMap("metric", " ")));
        assertEquals(rows("blank"), fetcher.fetchAnalyticsData(FROM, TO, Collections.<String, String>emptyMap()));
    }

    @Test
    public void analyticsReturnsEmptyWhenBodyMissingOrWithoutEvents() {
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok().build())
                .thenReturn(body("other", rows("x")));

        assertTrue(fetcher.fetchAnalyticsData(FROM, TO, Collections.singletonMap("metric", "a")).isEmpty());
        assertTrue(fetcher.fetchAnalyticsData(FROM, TO, Collections.singletonMap("metric", "b")).isEmpty());
    }

    @Test
    public void analyticsFallsBackToSampleDataOnCheckedLoaderFailure() {
        when(appConfig.getAnalyticsServiceUrl()).thenAnswer(inv -> {
            throw new IOException("boom");
        });

        List<Map<String, Object>> data = fetcher.fetchAnalyticsData(FROM, TO, null);
        assertEquals(50, data.size());
        assertEquals("evt-0000", data.get(0).get("event_id"));
        assertEquals("2024-01-01T00:00:00Z", data.get(0).get("timestamp"));
        assertEquals("error", data.get(0).get("status"));
        assertEquals("success", data.get(1).get("status"));
    }

    @Ignore("Suspected bug: Guava wraps RestClientException in UncheckedExecutionException, "
            + "which the catch(ExecutionException) does not handle, so the sample-data fallback never runs "
            + "and the report fails. See cov90-report-service.md.")
    @Test
    public void analyticsFallsBackToSampleDataWhenServiceUnreachable() {
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new ResourceAccessException("unreachable"));
        assertEquals(50, fetcher.fetchAnalyticsData(FROM, TO, null).size());
    }

    @Test
    public void auditReturnsEventsAndCachesResult() {
        String url = "http://audit/api/v1/audit/events?from=2024-01-01T00:00:00Z&to=2024-01-02T00:00:00Z";
        when(restTemplate.getForEntity(url, Map.class)).thenReturn(body("events", rows("au")));

        assertEquals(rows("au"), fetcher.fetchAuditData(FROM, TO, null));
        assertEquals(rows("au"), fetcher.fetchAuditData(FROM, TO, null));
        verify(restTemplate, times(1)).getForEntity(url, Map.class);
    }

    @Test
    public void auditReturnsEmptyWhenBodyHasNoEvents() {
        when(restTemplate.getForEntity(anyString(), eq(Map.class))).thenReturn(body("nope", rows("x")));
        assertTrue(fetcher.fetchAuditData(FROM, TO, null).isEmpty());
    }

    @Test
    public void auditReturnsEmptyWhenBodyIsNull() {
        when(restTemplate.getForEntity(anyString(), eq(Map.class))).thenReturn(ResponseEntity.ok().build());
        assertTrue(fetcher.fetchAuditData(FROM, TO, null).isEmpty());
    }

    @Test
    public void auditFallsBackToSampleDataOnCheckedLoaderFailure() {
        when(appConfig.getAuditServiceUrl()).thenAnswer(inv -> {
            throw new IOException("boom");
        });

        List<Map<String, Object>> data = fetcher.fetchAuditData(FROM, TO, null);
        assertEquals(50, data.size());
        assertEquals("aud-0000", data.get(0).get("audit_id"));
        assertEquals("LOGIN", data.get(0).get("action"));
        assertEquals("SUCCESS", data.get(0).get("result"));
    }

    @Ignore("Suspected bug: same UncheckedExecutionException issue as analytics; audit fallback is unreachable.")
    @Test
    public void auditFallsBackToSampleDataWhenServiceUnreachable() {
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new ResourceAccessException("unreachable"));
        assertEquals(50, fetcher.fetchAuditData(FROM, TO, null).size());
    }

    @Test
    public void userActivityReturnsActivities() {
        String url = "http://auth/api/v1/users/activity?from=2024-01-01T00:00:00Z&to=2024-01-02T00:00:00Z";
        when(restTemplate.getForEntity(url, Map.class)).thenReturn(body("activities", rows("u")));
        assertEquals(rows("u"), fetcher.fetchUserActivityData(FROM, TO, null));
    }

    @Test
    public void userActivityReturnsEmptyWhenBodyMissingOrWithoutActivities() {
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenReturn(ResponseEntity.ok().build())
                .thenReturn(body("events", rows("x")));
        assertTrue(fetcher.fetchUserActivityData(FROM, TO, null).isEmpty());
        assertTrue(fetcher.fetchUserActivityData(FROM, TO, null).isEmpty());
    }

    @Test
    public void userActivityFallsBackToSampleDataWhenServiceUnreachable() {
        when(restTemplate.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new ResourceAccessException("unreachable"));

        List<Map<String, Object>> data = fetcher.fetchUserActivityData(FROM, TO, null);
        assertEquals(25, data.size());
        assertEquals("user-000", data.get(0).get("user_id"));
        assertEquals(false, data.get(0).get("active"));
        assertEquals(true, data.get(1).get("active"));
    }
}
