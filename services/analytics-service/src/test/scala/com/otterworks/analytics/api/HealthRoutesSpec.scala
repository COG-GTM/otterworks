package com.otterworks.analytics.api

import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.AnalyticsEvent
import com.otterworks.analytics.repository.MetricsRepository
import com.otterworks.analytics.service.AnalyticsService
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import scala.concurrent.Future

/** Covers GET /health (healthy + degraded) and the Prometheus /metrics scrape. */
class HealthRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(50, Millis))

  private val pgConfig = PostgresConfig(
    url = "jdbc:postgresql://localhost:5432/test",
    user = "test",
    password = "test",
    maxPoolSize = 2
  )

  /** Re-exports the in-process repository, failing only the health probe's query. */
  private class FailingCountRepository(delegate: MetricsRepository) extends MetricsRepository:
    export delegate.{getEventCount as _, *}
    def getEventCount: Future[Long] = Future.failed(RuntimeException("db down"))

  private def routesWith(repo: MetricsRepository) = HealthRoutes(AnalyticsService(repo)).routes

  "GET /health" should "report healthy with the processed event count" in {
    Get("/health") ~> routesWith(MetricsRepository(pgConfig)) ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] shouldBe
        """{"status":"healthy","service":"analytics-service","eventsProcessed":0}"""
    }
  }

  it should "report the live event count once events have been stored" in {
    val repo = MetricsRepository(pgConfig)
    val service = AnalyticsService(repo)
    val routes = HealthRoutes(service).routes
    val stored = Future.sequence(List("document.created", "document.viewed").map { t =>
      repo.storeEvent(AnalyticsEvent.create(t, "u1", "d1", "document"))
    })
    whenReady(stored) { _ =>
      Get("/health") ~> routes ~> check {
        status shouldBe StatusCodes.OK
        responseAs[String] should include(""""eventsProcessed":2""")
      }
    }
  }

  it should "degrade to 503 when the repository query fails" in {
    Get("/health") ~> routesWith(FailingCountRepository(MetricsRepository(pgConfig))) ~> check {
      status shouldBe StatusCodes.ServiceUnavailable
      responseAs[String] shouldBe
        """{"status":"degraded","service":"analytics-service","eventsProcessed":0}"""
    }
  }

  "GET /metrics" should "expose the service counters in Prometheus text exposition format" in {
    // The collectors live in `object HealthRoutes`; universal-apply of the class does not
    // initialise the companion, so touch it before scraping the default registry.
    HealthRoutes.eventsReceivedTotal.labels("document.created").inc()
    HealthRoutes.activeConnections.set(3)
    HealthRoutes.requestDuration.labels("GET", "/health", "200").observe(0.01)

    Get("/metrics") ~> routesWith(MetricsRepository(pgConfig)) ~> check {
      status shouldBe StatusCodes.OK
      val body = responseAs[String]
      body should include("# TYPE analytics_events_received_total counter")
      body should include("""analytics_events_received_total{event_type="document.created",}""")
      body should include("analytics_active_connections 3.0")
      body should include("analytics_request_duration_seconds_count")
    }
  }
