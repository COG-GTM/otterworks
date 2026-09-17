package com.otterworks.analytics

import com.otterworks.analytics.api.HealthRoutes
import com.otterworks.analytics.config.AppConfig
import org.scalatest.concurrent.Eventually
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import java.net.URI
import java.net.http.{HttpClient, HttpRequest, HttpResponse}
import java.time.Duration

/**
 * Boots the real entrypoint against the test configuration (in-memory metrics
 * store, port 8088) and drives it over HTTP. `Main.main` blocks on the actor
 * system, so it runs on a daemon thread for the lifetime of the JVM.
 */
class MainSpec extends AnyFlatSpec with Matchers with Eventually:

  given PatienceConfig = PatienceConfig(timeout = Span(60, Seconds), interval = Span(250, Millis))

  private val baseUrl = s"http://localhost:${AppConfig.load().server.port}"
  private val client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build()

  private def get(path: String): HttpResponse[String] =
    client.send(
      HttpRequest.newBuilder(URI.create(s"$baseUrl$path")).GET().build(),
      HttpResponse.BodyHandlers.ofString()
    )

  private def postJson(path: String, body: String): HttpResponse[String] =
    client.send(
      HttpRequest
        .newBuilder(URI.create(s"$baseUrl$path"))
        .header("Content-Type", "application/json")
        .POST(HttpRequest.BodyPublishers.ofString(body))
        .build(),
      HttpResponse.BodyHandlers.ofString()
    )

  private lazy val started: Unit =
    val thread = new Thread(() => Main.main(Array.empty), "analytics-main-spec")
    thread.setDaemon(true)
    thread.start()
    eventually(get("/health").statusCode() shouldBe 200)

  "Main" should "boot and serve a healthy /health" in {
    started

    val response = get("/health")
    response.statusCode() shouldBe 200
    response.body() should include(""""status":"healthy"""")
    response.body() should include(""""service":"analytics-service"""")
  }

  it should "serve the analytics API backed by the configured store" in {
    started

    val accepted = postJson(
      "/api/v1/analytics/events",
      """{"eventType":"document.created","userId":"main-user","resourceId":"main-doc",
        |"resourceType":"document","metadata":{"title":"Boot check"}}""".stripMargin
    )
    accepted.statusCode() shouldBe 202

    eventually {
      val activity = get("/api/v1/analytics/users/main-user/activity")
      activity.statusCode() shouldBe 200
      activity.body() should include(""""totalEvents":1""")
      activity.body() should include("main-doc")
    }

    get("/api/v1/analytics/dashboard").statusCode() shouldBe 200
  }

  it should "answer 503 on the market endpoints when there is no durable store" in {
    started

    // The test config selects the in-memory backend, so margins/market are unavailable.
    for path <- List("/api/v1/analytics/margins", "/api/v1/analytics/market/series") do
      val response = get(path)
      withClue(s"$path: ") {
        response.statusCode() shouldBe 503
        response.body() should include("require the durable PostgreSQL store")
      }
  }

  it should "expose the Prometheus registry" in {
    started
    // Counters are only rendered once they have a sample, and the labels this
    // service uses are set by the ingestion path rather than by /metrics.
    HealthRoutes.eventsReceivedTotal.labels("main.spec.probe").inc()

    val response = get("/metrics")
    response.statusCode() shouldBe 200
    response.body() should include("""analytics_events_received_total{event_type="main.spec.probe",} 1.0""")
  }
