package com.otterworks.report.service;

import com.otterworks.report.config.AppConfig;
import org.junit.Before;
import org.junit.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import java.net.URI;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.queryParam;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * Verifies that report parameters cannot inject extra query parameters into the
 * internal analytics-service request built by {@link ReportDataFetcher}.
 */
public class ReportDataFetcherTest {

    private static final Date FROM = new Date(1_700_000_000_000L);
    private static final Date TO = new Date(1_700_086_400_000L);

    private RestTemplate restTemplate;
    private MockRestServiceServer server;
    private ReportDataFetcher fetcher;

    @Before
    public void setUp() {
        restTemplate = new RestTemplate();
        server = MockRestServiceServer.bindTo(restTemplate).build();
        AppConfig appConfig = new AppConfig();
        ReflectionTestUtils.setField(appConfig, "analyticsServiceUrl", "http://analytics-service:8088");
        fetcher = new ReportDataFetcher(restTemplate, appConfig);
    }

    @Test
    public void allowedMetricIsSentAsSingleQueryParameter() {
        server.expect(requestTo("http://analytics-service:8088/api/v1/analytics/events"
                        + "?from=2023-11-14T22%3A13%3A20Z&to=2023-11-15T22%3A13%3A20Z&metric=document.created"))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess("{\"events\":[{\"event_id\":\"evt-1\"}]}", MediaType.APPLICATION_JSON));

        List<Map<String, Object>> rows = fetcher.fetchAnalyticsData(FROM, TO,
                Collections.singletonMap("metric", "document.created"));

        server.verify();
        assertEquals(1, rows.size());
        assertEquals("evt-1", rows.get(0).get("event_id"));
    }

    @Test
    public void metricWithQuerySeparatorsIsRejectedWithoutCallingAnalytics() {
        try {
            fetcher.fetchAnalyticsData(FROM, TO,
                    Collections.singletonMap("metric", "x&from=2000-01-01&user_id=alice"));
            fail("expected IllegalArgumentException");
        } catch (IllegalArgumentException expected) {
            assertEquals("Invalid analytics metric parameter", expected.getMessage());
        }
        server.verify();
    }

    @Test
    public void blankMetricIsOmitted() {
        server.expect(requestTo("http://analytics-service:8088/api/v1/analytics/events"
                        + "?from=2023-11-14T22%3A13%3A20Z&to=2023-11-15T22%3A13%3A20Z"))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess("{\"events\":[]}", MediaType.APPLICATION_JSON));

        fetcher.fetchAnalyticsData(FROM, TO, Collections.singletonMap("metric", "  "));

        server.verify();
    }

    @Test
    public void reservedCharactersAreEncodedIntoOneValue() {
        URI uri = fetcher.buildAnalyticsEventsUri(FROM, TO, "a&b=c#d+e");

        assertTrue(uri.getRawQuery(), uri.getRawQuery().endsWith("&metric=a%26b%3Dc%23d%2Be"));
        assertEquals(null, uri.getRawFragment());
        Map<String, List<String>> params = UriComponentsBuilder.fromUri(uri).build().getQueryParams();
        assertEquals(3, params.size());
        assertFalse(params.containsKey("b"));
        assertEquals(Collections.singletonList("a%26b%3Dc%23d%2Be"), params.get("metric"));
    }

    @Test
    public void analyticsRequestReceivesInjectedValueAsSingleMetric() {
        server.expect(queryParam("metric", "a%26b%3Dc"))
                .andRespond(withSuccess("{\"events\":[]}", MediaType.APPLICATION_JSON));

        restTemplate.getForEntity(fetcher.buildAnalyticsEventsUri(FROM, TO, "a&b=c"), Map.class);

        server.verify();
    }
}
