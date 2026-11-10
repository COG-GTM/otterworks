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

    long start = System.nanoTime();
    newClient(audit.baseUrl(), 200).emit(loginEvent());
    long elapsedMs = (System.nanoTime() - start) / 1_000_000;

    assertThat(elapsedMs).isLessThan(150);
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
}
