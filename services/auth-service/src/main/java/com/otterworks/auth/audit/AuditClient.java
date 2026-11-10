package com.otterworks.auth.audit;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.annotation.PreDestroy;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

/**
 * Fire-and-forget emitter for audit-service. {@link #emit} captures the request context on the
 * calling thread and hands delivery to a small bounded executor, so a slow or unavailable
 * audit-service never affects the user's request. Failed deliveries are logged and counted in
 * {@code audit_emit_failures_total}.
 */
@Component
public class AuditClient {

  static final String EVENTS_PATH = "/api/v1/audit/events";
  static final String FAILURE_METRIC = "audit.emit.failures";

  private static final Logger log = LoggerFactory.getLogger(AuditClient.class);

  private final String serviceName;
  private final String token;
  private final int maxRetries;
  private final RestClient restClient;
  private final ObjectMapper objectMapper;
  private final MeterRegistry meterRegistry;
  private final ThreadPoolExecutor executor;

  public AuditClient(
      @Value("${audit.service-url:}") String serviceUrl,
      @Value("${audit.token:}") String token,
      @Value("${audit.timeout-ms:2000}") int timeoutMs,
      @Value("${audit.max-retries:1}") int maxRetries,
      @Value("${audit.queue-capacity:1000}") int queueCapacity,
      @Value("${spring.application.name:auth-service}") String serviceName,
      ObjectMapper objectMapper,
      MeterRegistry meterRegistry) {
    this.serviceName = serviceName;
    this.token = token;
    this.maxRetries = Math.max(0, maxRetries);
    this.objectMapper = objectMapper;
    this.meterRegistry = meterRegistry;
    Counter.builder(FAILURE_METRIC)
        .description("Audit events that could not be delivered to audit-service")
        .tag("reason", "unavailable")
        .register(meterRegistry);

    if (serviceUrl == null || serviceUrl.isBlank()) {
      log.warn("AUDIT_SERVICE_URL is not set; audit events will not be emitted");
      this.restClient = null;
      this.executor = null;
      return;
    }

    SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
    requestFactory.setConnectTimeout(timeoutMs);
    requestFactory.setReadTimeout(timeoutMs);
    this.restClient =
        RestClient.builder()
            .baseUrl(serviceUrl.replaceAll("/+$", ""))
            .requestFactory(requestFactory)
            .build();

    AtomicInteger threadCount = new AtomicInteger();
    this.executor =
        new ThreadPoolExecutor(
            1,
            2,
            30,
            TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(Math.max(1, queueCapacity)),
            runnable -> {
              Thread thread = new Thread(runnable, "audit-emit-" + threadCount.incrementAndGet());
              thread.setDaemon(true);
              return thread;
            },
            new ThreadPoolExecutor.AbortPolicy());
  }

  public boolean isEnabled() {
    return restClient != null;
  }

  /** Enriches the event with request context and queues it for delivery. Never throws. */
  public void emit(AuditEvent event) {
    if (!isEnabled() || event == null) {
      return;
    }
    try {
      AuditEvent enriched = enrich(event, AuditRequestContext.current());
      executor.execute(() -> deliver(enriched));
    } catch (RejectedExecutionException e) {
      recordFailure("queue_full", event, e);
    } catch (RuntimeException e) {
      recordFailure("emit_error", event, e);
    }
  }

  AuditEvent enrich(AuditEvent event, AuditRequestContext context) {
    AuditEvent.AuditEventBuilder builder = event.toBuilder();
    if (event.getIpAddress() == null) {
      builder.ipAddress(context.ipAddress());
    }
    if (event.getUserAgent() == null) {
      builder.userAgent(context.userAgent());
    }
    if (event.getRequestId() == null) {
      builder.requestId(context.requestId());
    }
    if (event.getServiceName() == null) {
      builder.serviceName(serviceName);
    }
    if (event.getTimestamp() == null) {
      builder.timestamp(Instant.now().truncatedTo(ChronoUnit.MILLIS).toString());
    }
    return builder.build();
  }

  void deliver(AuditEvent event) {
    String body;
    try {
      body = objectMapper.writeValueAsString(event);
    } catch (JsonProcessingException e) {
      recordFailure("serialization", event, e);
      return;
    }

    RuntimeException lastError = null;
    for (int attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        restClient
            .post()
            .uri(EVENTS_PATH)
            .contentType(MediaType.APPLICATION_JSON)
            .headers(
                headers -> {
                  if (token != null && !token.isBlank()) {
                    headers.set("X-Audit-Token", token);
                  }
                  if (event.getRequestId() != null) {
                    headers.set("X-Request-ID", event.getRequestId());
                  }
                })
            .body(body)
            .retrieve()
            .toBodilessEntity();
        return;
      } catch (HttpClientErrorException e) {
        // 4xx (bad token, invalid event) will not succeed on retry.
        recordFailure("rejected_" + e.getStatusCode().value(), event, e);
        return;
      } catch (RuntimeException e) {
        lastError = e;
        if (attempt < maxRetries) {
          sleepBeforeRetry(attempt);
        }
      }
    }
    recordFailure("unavailable", event, lastError);
  }

  private void sleepBeforeRetry(int attempt) {
    try {
      Thread.sleep(100L * (attempt + 1));
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
    }
  }

  private void recordFailure(String reason, AuditEvent event, Exception error) {
    meterRegistry.counter(FAILURE_METRIC, "reason", reason).increment();
    log.warn(
        "Failed to emit audit event action={} reason={} requestId={}: {}",
        event.getAction(),
        reason,
        event.getRequestId(),
        error == null ? "n/a" : error.getMessage());
  }

  @PreDestroy
  void shutdown() {
    if (executor == null) {
      return;
    }
    executor.shutdown();
    try {
      if (!executor.awaitTermination(2, TimeUnit.SECONDS)) {
        executor.shutdownNow();
      }
    } catch (InterruptedException e) {
      executor.shutdownNow();
      Thread.currentThread().interrupt();
    }
  }
}
