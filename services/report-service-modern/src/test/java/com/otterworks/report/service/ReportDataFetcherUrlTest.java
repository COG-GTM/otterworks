package com.otterworks.report.service;

import org.junit.jupiter.api.Test;

import java.net.URI;
import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;

class ReportDataFetcherUrlTest {

    private static final Instant FROM = Instant.parse("2026-01-01T00:00:00Z");
    private static final Instant TO = Instant.parse("2026-01-31T00:00:00Z");

    @Test
    void metricCannotInjectOrOverrideQueryParameters() {
        String url = ReportDataFetcher.upstreamUrl("http://analytics:8088", "/api/v1/analytics/events",
                FROM, TO, "views&from=1970-01-01T00:00:00Z");
        URI uri = URI.create(url);
        assertEquals("from=2026-01-01T00%3A00%3A00Z&to=2026-01-31T00%3A00%3A00Z&metric=views%26from%3D1970-01-01T00%3A00%3A00Z",
                uri.getRawQuery());
    }

    @Test
    void urlWithoutMetricHasOnlyDateParameters() {
        assertEquals("http://audit:8090/api/v1/audit/events?from=2026-01-01T00%3A00%3A00Z&to=2026-01-31T00%3A00%3A00Z",
                ReportDataFetcher.upstreamUrl("http://audit:8090", "/api/v1/audit/events", FROM, TO, null));
    }
}
