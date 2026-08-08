package com.otterworks.analytics.api

import akka.http.scaladsl.model.{ContentTypes, StatusCodes}
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.repository.{InMemoryMetricsRepository, UnavailableMetricsRepository}
import com.otterworks.analytics.service.AnalyticsService
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

/** GET /health (healthy + degraded) and the Prometheus /metrics exposition. */
class HealthRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(100, Millis))

  private val pgConfig = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)

  private def healthyRoutes(): (HealthRoutes, AnalyticsService) =
    val service = AnalyticsService(new InMemoryMetricsRepository(pgConfig))
    (HealthRoutes(service), service)

  "GET /health" should "report the number of processed events" in {
    val (routes, service) = healthyRoutes()
    service.trackEvent("document.created", "user-1", "doc-1", "document", Map.empty).futureValue

    Get("/health") ~> routes.routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`application/json`
      responseAs[String] shouldBe
        """{"status":"healthy","service":"analytics-service","eventsProcessed":1}"""
    }
  }

  it should "report degraded with 503 when the metrics store is unavailable" in {
    val routes = HealthRoutes(AnalyticsService(new UnavailableMetricsRepository))

    Get("/health") ~> routes.routes ~> check {
      status shouldBe StatusCodes.ServiceUnavailable
      responseAs[String] should include(""""status":"degraded"""")
    }
  }

  "GET /metrics" should "expose the registered Prometheus collectors" in {
    val (routes, _) = healthyRoutes()
    HealthRoutes.eventsReceivedTotal.labels("document.created").inc()
    HealthRoutes.requestDuration.labels("GET", "/health", "200").observe(0.01)
    HealthRoutes.activeConnections.set(3)

    Get("/metrics") ~> routes.routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`text/plain(UTF-8)`
      val body = responseAs[String]
      body should include("""analytics_events_received_total{event_type="document.created",} 1.0""")
      body should include("analytics_request_duration_seconds_count")
      body should include("analytics_active_connections 3.0")
    }
  }
