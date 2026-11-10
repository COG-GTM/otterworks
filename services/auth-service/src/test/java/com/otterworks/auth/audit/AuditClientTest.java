package com.otterworks.auth.audit;

import static com.github.tomakehurst.wiremock.client.WireMock.*;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.wireMockConfig;
import static org.assertj.core.api.Assertions.*;
import static org.awaitility.Awaitility.await;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.tomakehurst.wiremock.junit5.WireMockExtension;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.time.Duration;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionSynchronizationUtils;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

class AuditClientTest {

  @RegisterExtension
  static WireMockExtension audit =
      WireMockExtension.newInstance().options(wireMockConfig().dynamicPort()).build();

  private final ObjectMapper objectMapper = new ObjectMapper();
  private final SimpleMeterRegistry meterRegistry = new SimpleMeterRegistry();
  private AuditClient client;

  @AfterEach
  void tearDown() {
    if (client != null) {
      client.shutdown();
    }
    RequestContextHolder.resetRequestAttributes();
    if (TransactionSynchronizationManager.isSynchronizationActive()) {
      TransactionSynchronizationManager.clearSynchronization();
    }
  }

  private AuditClient newClient(String url, int timeoutMs) {
    client =
        new AuditClient(
            url, "dev-token", timeoutMs, 1, 100, "auth-service", objectMapper, meterRegistry);
    return client;
  }

  private static AuditEvent loginEvent() {
    return AuditEvent.builder()
        .userId("user-1")
        .actorType("user")
        .action("auth.login.success")
        .resourceType("user")
        .resourceId("user-1")
        .outcome("success")
        .details(Map.of("k", "v"))
        .build();
  }

  private double failures() {
    return meterRegistry.find(AuditClient.FAILURE_METRIC).counters().stream()
        .mapToDouble(Counter::count)
        .sum();
  }

  private void bindRequest(MockHttpServletRequest request) {
    RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
  }

  @Test
  void emit_postsContractPayloadWithHeadersAndRequestContext() throws Exception {
    audit.stubFor(post(AuditClient.EVENTS_PATH).willReturn(aResponse().withStatus(201)));
    MockHttpServletRequest request = new MockHttpServletRequest();
    request.addHeader("X-Forwarded-For", "203.0.113.7, 10.0.0.1");
    request.addHeader("X-Request-ID", "req-123");
    request.addHeader("User-Agent", "JUnit");
    bindRequest(request);

    newClient(audit.baseUrl(), 1000).emit(loginEvent());

    await()
        .atMost(Duration.ofSeconds(5))
        .untilAsserted(
            () -> audit.verify(1, postRequestedFor(urlEqualTo(AuditClient.EVENTS_PATH))));
    audit.verify(
        postRequestedFor(urlEqualTo(AuditClient.EVENTS_PATH))
            .withHeader("Content-Type", containing("application/json"))
            .withHeader("X-Audit-Token", equalTo("dev-token"))
            .withHeader("X-Request-ID", equalTo("req-123")));

    JsonNode body =
        objectMapper.readTree(audit.getAllServeEvents().get(0).getRequest().getBodyAsString());
    assertThat(body.get("userId").asText()).isEqualTo("user-1");
    assertThat(body.get("action").asText()).isEqualTo("auth.login.success");
    assertThat(body.get("outcome").asText()).isEqualTo("success");
    assertThat(body.get("ipAddress").asText()).isEqualTo("203.0.113.7");
    assertThat(body.get("userAgent").asText()).isEqualTo("JUnit");
    assertThat(body.get("requestId").asText()).isEqualTo("req-123");
    assertThat(body.get("serviceName").asText()).isEqualTo("auth-service");
    assertThat(body.get("timestamp").asText()).matches("\\d{4}-\\d{2}-\\d{2}T.*Z");
    assertThat(body.get("details").get("k").asText()).isEqualTo("v");
    assertThat(body.has("tenantId")).as("null fields are omitted").isFalse();
    assertThat(failures()).isZero();
  }

  @Test
  void emit_retriesOnceOn5xxThenCountsFailure() {
    audit.stubFor(post(AuditClient.EVENTS_PATH).willReturn(aResponse().withStatus(503)));

    newClient(audit.baseUrl(), 1000).emit(loginEvent());

    await().atMost(Duration.ofSeconds(5)).until(() -> failures() == 1.0);
    audit.verify(2, postRequestedFor(urlEqualTo(AuditClient.EVENTS_PATH)));
  }

  @Test
  void emit_doesNotRetry4xx() {
    audit.stubFor(post(AuditClient.EVENTS_PATH).willReturn(aResponse().withStatus(401)));

    newClient(audit.baseUrl(), 1000).emit(loginEvent());

    await().atMost(Duration.ofSeconds(5)).until(() -> failures() == 1.0);
    audit.verify(1, postRequestedFor(urlEqualTo(AuditClient.EVENTS_PATH)));
  }

  @Test
  void emit_returnsImmediatelyWhenAuditServiceIsSlow() {
    audit.stubFor(
        post(AuditClient.EVENTS_PATH).willReturn(aResponse().withStatus(201).withFixedDelay(3000)));

    AuditClient c = newClient(audit.baseUrl(), 200);
    long start = System.nanoTime();
    c.emit(loginEvent());
    long elapsedMs = (System.nanoTime() - start) / 1_000_000;

    // The stub delays 3s; emit must return well before that regardless of CI jitter.
    assertThat(elapsedMs).isLessThan(1000);
    await().atMost(Duration.ofSeconds(5)).until(() -> failures() == 1.0);
  }

  @Test
  void emit_countsFailureWhenAuditServiceIsDown() {
    newClient("http://127.0.0.1:1", 200).emit(loginEvent());

    await().atMost(Duration.ofSeconds(5)).until(() -> failures() == 1.0);
  }

  @Test
  void emit_isNoOpWhenUrlUnset() {
    AuditClient disabled = newClient("", 200);

    assertThat(disabled.isEnabled()).isFalse();
    assertThatCode(() -> disabled.emit(loginEvent())).doesNotThrowAnyException();
    assertThat(audit.getAllServeEvents()).isEmpty();
  }

  @Test
  void clientIp_prefersForwardedForThenRealIpThenRemoteAddr() {
    MockHttpServletRequest request = new MockHttpServletRequest();
    request.setRemoteAddr("10.1.1.1");
    assertThat(AuditRequestContext.clientIp(request)).isEqualTo("10.1.1.1");

    request.addHeader("X-Real-IP", "198.51.100.2");
    assertThat(AuditRequestContext.clientIp(request)).isEqualTo("198.51.100.2");

    request.addHeader("X-Forwarded-For", " 203.0.113.9 , 198.51.100.2");
    assertThat(AuditRequestContext.clientIp(request)).isEqualTo("203.0.113.9");
  }

  @Test
  void emit_successInsideTransaction_isSentOnlyAfterCommit() throws Exception {
    audit.stubFor(post(AuditClient.EVENTS_PATH).willReturn(aResponse().withStatus(201)));
    AuditClient c = newClient(audit.baseUrl(), 1000);
    TransactionSynchronizationManager.initSynchronization();

    c.emit(loginEvent());
    Thread.sleep(300);
    audit.verify(0, postRequestedFor(urlEqualTo(AuditClient.EVENTS_PATH)));

    TransactionSynchronizationUtils.triggerAfterCommit();
    await()
        .atMost(Duration.ofSeconds(5))
        .untilAsserted(
            () -> audit.verify(1, postRequestedFor(urlEqualTo(AuditClient.EVENTS_PATH))));
  }

  @Test
  void emit_successInRolledBackTransaction_isNotSent() throws Exception {
    audit.stubFor(post(AuditClient.EVENTS_PATH).willReturn(aResponse().withStatus(201)));
    AuditClient c = newClient(audit.baseUrl(), 1000);
    TransactionSynchronizationManager.initSynchronization();

    c.emit(loginEvent());
    TransactionSynchronizationUtils.triggerAfterCompletion(
        TransactionSynchronization.STATUS_ROLLED_BACK);
    Thread.sleep(300);

    audit.verify(0, postRequestedFor(urlEqualTo(AuditClient.EVENTS_PATH)));
  }

  @Test
  void emit_failureInsideTransaction_isSentImmediately() {
    audit.stubFor(post(AuditClient.EVENTS_PATH).willReturn(aResponse().withStatus(201)));
    AuditClient c = newClient(audit.baseUrl(), 1000);
    TransactionSynchronizationManager.initSynchronization();

    c.emit(loginEvent().toBuilder().action("auth.login.failure").outcome("failure").build());

    await()
        .atMost(Duration.ofSeconds(5))
        .untilAsserted(
            () -> audit.verify(1, postRequestedFor(urlEqualTo(AuditClient.EVENTS_PATH))));
  }
}
