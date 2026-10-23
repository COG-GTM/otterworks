package com.otterworks.report.qa;

import com.otterworks.report.config.AppConfig;
import com.otterworks.report.service.ReportDataFetcher;
import com.google.common.util.concurrent.UncheckedExecutionException;
import org.junit.Before;
import org.junit.Ignore;
import org.junit.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestTemplate;

import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.startsWith;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThat;
import static org.junit.Assert.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** QA audit: ReportDataFetcher upstream contract, caching and fallback behaviour. */
public class QaReportDataFetcherTest {

    private RestTemplate rest;
    private ReportDataFetcher fetcher;
    private final Date from = new Date(1_767_225_600_000L); // 2026-01-01T00:00:00Z
    private final Date to = new Date(1_767_312_000_000L);   // 2026-01-02T00:00:00Z

    @Before
    public void setUp() {
        rest = mock(RestTemplate.class);
        AppConfig cfg = mock(AppConfig.class);
        when(cfg.getAnalyticsServiceUrl()).thenReturn("http://analytics");
        when(cfg.getAuditServiceUrl()).thenReturn("http://audit");
        when(cfg.getAuthServiceUrl()).thenReturn("http://auth");
        fetcher = new ReportDataFetcher(rest, cfg);
    }

    private static ResponseEntity<Map> body(String key, Object value) {
        Map<String, Object> m = new HashMap<>();
        m.put(key, value);
        return new ResponseEntity<>(m, HttpStatus.OK);
    }

    @Test
    public void analyticsFetchPassesRangeAndMetricAndCachesSuccess() {
        List<Map<String, Object>> events = Collections.singletonList(Collections.singletonMap("event_id", "e1"));
        when(rest.getForEntity(anyString(), eq(Map.class))).thenReturn(body("events", events));
        Map<String, String> params = Collections.singletonMap("metric", "views");

        assertEquals(events, fetcher.fetchAnalyticsData(from, to, params));
        assertEquals(events, fetcher.fetchAnalyticsData(from, to, params));

        ArgumentCaptor<String> url = ArgumentCaptor.forClass(String.class);
        verify(rest, times(1)).getForEntity(url.capture(), eq(Map.class));
        assertThat(url.getValue(), startsWith("http://analytics/api/v1/analytics/events?"));
        assertThat(url.getValue(), containsString("from=2026-01-01T00:00:00Z"));
        assertThat(url.getValue(), containsString("to=2026-01-02T00:00:00Z"));
        assertThat(url.getValue(), containsString("metric=views"));
    }

    @Ignore("Finding RPT-1: Guava wraps the RestClientException in UncheckedExecutionException, which the "
            + "catch (ExecutionException) in fetchAnalyticsData/fetchAuditData does not handle, so the documented "
            + "sample-data fallback never runs and the report is marked FAILED")
    @Test
    public void analyticsFallbackIsUsedAndNotCachedWhenUpstreamFails() {
        when(rest.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new HttpClientErrorException(HttpStatus.METHOD_NOT_ALLOWED));
        assertEquals(50, fetcher.fetchAnalyticsData(from, to, null).size());
        fetcher.fetchAnalyticsData(from, to, null);
        verify(rest, times(2)).getForEntity(anyString(), eq(Map.class));
    }

    @Test
    public void analyticsUpstreamErrorCurrentlyEscapesFetcher() {
        when(rest.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new HttpClientErrorException(HttpStatus.METHOD_NOT_ALLOWED));
        try {
            fetcher.fetchAnalyticsData(from, to, null);
            throw new AssertionError("RPT-1 appears fixed: remove this test and un-ignore the fallback test");
        } catch (UncheckedExecutionException expected) {
            assertTrue(expected.getCause() instanceof HttpClientErrorException);
        }
    }

    @Test
    public void userActivityFallsBackToSampleRowsOnRestError() {
        when(rest.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new HttpClientErrorException(HttpStatus.SERVICE_UNAVAILABLE));
        assertEquals(25, fetcher.fetchUserActivityData(from, to, null).size());
    }

    @Ignore("Finding RPT-4: user-activity fallback fabricates 25 sample users with last_login = daysAgo(i % 7), "
            + "ignoring the requested dateFrom/dateTo, and the report is marked COMPLETED as if the data were real")
    @Test
    public void userActivityFallbackRowsStayInsideRequestedRange() {
        when(rest.getForEntity(anyString(), eq(Map.class)))
                .thenThrow(new HttpClientErrorException(HttpStatus.FORBIDDEN));
        for (Map<String, Object> row : fetcher.fetchUserActivityData(from, to, null)) {
            Date lastLogin = com.otterworks.report.util.ReportDateUtils.parseIsoDate((String) row.get("last_login"));
            assertTrue("last_login " + row.get("last_login") + " outside range",
                    !lastLogin.before(from) && !lastLogin.after(to));
        }
    }

    @Test
    public void auditAndUserActivityParseTheirEnvelopes() {
        List<Map<String, Object>> rows = Collections.singletonList(Collections.singletonMap("k", "v"));
        when(rest.getForEntity(org.mockito.ArgumentMatchers.startsWith("http://audit/api/v1/audit/events"), eq(Map.class))).thenReturn(body("events", rows));
        when(rest.getForEntity(org.mockito.ArgumentMatchers.startsWith("http://auth/api/v1/users/activity"), eq(Map.class))).thenReturn(body("activities", rows));
        assertEquals(rows, fetcher.fetchAuditData(from, to, null));
        assertEquals(rows, fetcher.fetchUserActivityData(from, to, null));
    }

    @Test
    public void missingEnvelopeKeyYieldsEmptyList() {
        when(rest.getForEntity(anyString(), eq(Map.class))).thenReturn(body("unexpected", 1));
        assertTrue(fetcher.fetchUserActivityData(from, to, null).isEmpty());
    }
}
