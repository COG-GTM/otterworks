package com.otterworks.report.service;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.otterworks.report.config.ReportProperties;
import com.otterworks.report.util.ReportDateUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.util.UriComponentsBuilder;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Fetches report rows from the analytics, audit, and auth services via {@link RestClient},
 * caching successful upstream responses in Caffeine (5 min TTL, 100 entries). When an upstream call
 * fails, sample data is returned and nothing is cached so the next request retries the upstream.
 */
@Service
public class ReportDataFetcher {

    private static final Logger logger = LoggerFactory.getLogger(ReportDataFetcher.class);
    private static final ParameterizedTypeReference<Map<String, Object>> JSON_OBJECT =
            new ParameterizedTypeReference<>() { };

    private final RestClient restClient;
    private final ReportProperties properties;
    private final Cache<String, List<Map<String, Object>>> dataCache = Caffeine.newBuilder()
            .maximumSize(100)
            .expireAfterWrite(Duration.ofMinutes(5))
            .build();

    public ReportDataFetcher(RestClient reportRestClient, ReportProperties properties) {
        this.restClient = reportRestClient;
        this.properties = properties;
    }

    public List<Map<String, Object>> fetchAnalyticsData(Instant dateFrom, Instant dateTo, Map<String, String> parameters) {
        String metric = parameters != null ? parameters.get("metric") : null;
        String cacheKey = "analytics:" + ReportDateUtils.toIsoString(dateFrom) + ":" + ReportDateUtils.toIsoString(dateTo)
                + (metric != null ? ":metric=" + metric : "");
        String url = upstreamUrl(properties.analyticsServiceUrl(), "/api/v1/analytics/events", dateFrom, dateTo,
                metric != null && !metric.isBlank() ? metric : null);
        return cachedOrFallback(cacheKey, () -> {
            logger.info("Fetching analytics data from: {}", url);
            return listField(url, "events");
        }, () -> generateSampleAnalyticsData(dateFrom), "analytics");
    }

    public List<Map<String, Object>> fetchAuditData(Instant dateFrom, Instant dateTo, Map<String, String> parameters) {
        String cacheKey = "audit:" + ReportDateUtils.toIsoString(dateFrom) + ":" + ReportDateUtils.toIsoString(dateTo);
        String url = upstreamUrl(properties.auditServiceUrl(), "/api/v1/audit/events", dateFrom, dateTo, null);
        return cachedOrFallback(cacheKey, () -> {
            logger.info("Fetching audit data from: {}", url);
            return listField(url, "events");
        }, () -> generateSampleAuditData(dateFrom), "audit");
    }

    public List<Map<String, Object>> fetchUserActivityData(Instant dateFrom, Instant dateTo, Map<String, String> parameters) {
        String url = upstreamUrl(properties.authServiceUrl(), "/api/v1/users/activity", dateFrom, dateTo, null);
        logger.info("Fetching user activity from: {}", url);
        try {
            return listField(url, "activities");
        } catch (RestClientException e) {
            logger.error("Failed to fetch user activity data: {}", e.getMessage());
            return generateSampleUserActivityData();
        }
    }

    private List<Map<String, Object>> cachedOrFallback(String cacheKey,
                                                       Supplier<List<Map<String, Object>>> upstream,
                                                       Supplier<List<Map<String, Object>>> fallback,
                                                       String source) {
        try {
            return dataCache.get(cacheKey, key -> upstream.get());
        } catch (RestClientException e) {
            logger.error("Failed to fetch {} data, using sample data: {}", source, e.getMessage());
            return fallback.get();
        }
    }

    @SuppressWarnings("unchecked")
    /** Query values are percent-encoded so caller input (e.g. "metric") cannot add or override parameters. */
    static String upstreamUrl(String baseUrl, String path, Instant dateFrom, Instant dateTo, String metric) {
        UriComponentsBuilder builder = UriComponentsBuilder.fromUriString(baseUrl).path(path)
                .queryParam("from", "{from}")
                .queryParam("to", "{to}");
        Map<String, Object> vars = new HashMap<>();
        vars.put("from", ReportDateUtils.toIsoString(dateFrom));
        vars.put("to", ReportDateUtils.toIsoString(dateTo));
        if (metric != null) {
            builder.queryParam("metric", "{metric}");
            vars.put("metric", metric);
        }
        return builder.encode().buildAndExpand(vars).toUriString();
    }

    private List<Map<String, Object>> listField(String url, String field) {
        Map<String, Object> body = restClient.get().uri(java.net.URI.create(url)).retrieve().body(JSON_OBJECT);
        if (body != null && body.get(field) instanceof List<?> rows) {
            return (List<Map<String, Object>>) rows;
        }
        return List.of();
    }

    private List<Map<String, Object>> generateSampleAnalyticsData(Instant dateFrom) {
        List<Map<String, Object>> data = new ArrayList<>();
        String[] events = {"file_upload", "file_download", "doc_create", "doc_edit", "doc_share", "search_query"};
        String[] users = {"user-001", "user-002", "user-003", "user-004", "user-005"};
        for (int i = 0; i < 50; i++) {
            Map<String, Object> row = new HashMap<>();
            row.put("event_id", "evt-%04d".formatted(i));
            row.put("event_type", events[i % events.length]);
            row.put("user_id", users[i % users.length]);
            row.put("timestamp", ReportDateUtils.toIsoString(dateFrom.plus(Duration.ofHours(i))));
            row.put("duration_ms", 100 + (i * 17) % 5000);
            row.put("status", i % 10 == 0 ? "error" : "success");
            row.put("metadata", "sample-analytics-row-" + i);
            data.add(row);
        }
        return data;
    }

    private List<Map<String, Object>> generateSampleAuditData(Instant dateFrom) {
        List<Map<String, Object>> data = new ArrayList<>();
        String[] actions = {"LOGIN", "LOGOUT", "FILE_ACCESS", "PERMISSION_CHANGE", "ADMIN_ACTION", "API_CALL"};
        String[] results = {"SUCCESS", "FAILURE", "DENIED"};
        for (int i = 0; i < 50; i++) {
            Map<String, Object> row = new HashMap<>();
            row.put("audit_id", "aud-%04d".formatted(i));
            row.put("action", actions[i % actions.length]);
            row.put("actor", "user-%03d".formatted(i % 10));
            row.put("result", results[i % results.length]);
            row.put("ip_address", "192.168.1." + (i % 255));
            row.put("timestamp", ReportDateUtils.toIsoString(dateFrom.plus(Duration.ofMinutes(30L * i))));
            row.put("resource", "/files/doc-" + (i % 20));
            row.put("details", "Audit entry " + i);
            data.add(row);
        }
        return data;
    }

    private List<Map<String, Object>> generateSampleUserActivityData() {
        List<Map<String, Object>> data = new ArrayList<>();
        for (int i = 0; i < 25; i++) {
            Map<String, Object> row = new HashMap<>();
            row.put("user_id", "user-%03d".formatted(i));
            row.put("email", "user" + i + "@otterworks.example.com");
            row.put("last_login", ReportDateUtils.toIsoString(ReportDateUtils.daysAgo(i % 7)));
            row.put("files_uploaded", 10 + i * 3);
            row.put("docs_created", 5 + i * 2);
            row.put("storage_used_mb", 100 + i * 50);
            row.put("collaborations", i * 4);
            row.put("active", i % 5 != 0);
            data.add(row);
        }
        return data;
    }
}
