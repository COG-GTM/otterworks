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

import scala.concurrent.Future

class HealthRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  private val pgConfig = PostgresConfig(
    url = "jdbc:postgresql://localhost:5432/test",
    user = "test",
    password = "test",
    maxPoolSize = 2
  )

  /** Fails only `getEventCount`; every other member is re-exported from the in-process repo. */
  private class FailingCountRepository(delegate: MetricsRepository) extends MetricsRepository:
    export delegate.{getEventCount as _, *}
    def getEventCount: Future[Long] = Future.failed(RuntimeException("db down"))

  private def routesFor(repo: MetricsRepository) = HealthRoutes(AnalyticsService(repo)).routes

  "GET /health" should "report healthy with a zero event count on a fresh repository" in {
    Get("/health") ~> routesFor(MetricsRepository(pgConfig)) ~> check {
      status shouldBe StatusCodes.OK
      val body = responseAs[String]
      body should include(""""status":"healthy"""")
      body should include(""""service":"analytics-service"""")
      body should include(""""eventsProcessed":0""")
    }
  }

  it should "report the number of events the repository has stored" in {
    val repo = MetricsRepository(pgConfig)
    val service = AnalyticsService(repo)
    (1 to 3).foreach { i =>
      repo.storeEvent(AnalyticsEvent.create("document.viewed", s"u$i", s"d$i", "document", Map.empty)).futureValue
    }

    Get("/health") ~> HealthRoutes(service).routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] should include(""""eventsProcessed":3""")
    }
  }

  it should "answer 503 degraded when the repository lookup fails" in {
    Get("/health") ~> routesFor(FailingCountRepository(MetricsRepository(pgConfig))) ~> check {
      status shouldBe StatusCodes.ServiceUnavailable
      val body = responseAs[String]
      body should include(""""status":"degraded"""")
      body should include(""""eventsProcessed":0""")
    }
  }

  "GET /metrics" should "render the Prometheus text exposition format" in {
    // The collectors live in `object HealthRoutes`; constructing the class does not
    // initialise the companion, so touch a counter before scraping the registry.
    HealthRoutes.eventsReceivedTotal.labels("document.created").inc()
    HealthRoutes.activeConnections.set(2)
    HealthRoutes.requestDuration.labels("GET", "/health", "200").observe(0.01)

    Get("/metrics") ~> routesFor(MetricsRepository(pgConfig)) ~> check {
      status shouldBe StatusCodes.OK
      val body = responseAs[String]
      body should include("# TYPE analytics_events_received_total counter")
      body should include("""analytics_events_received_total{event_type="document.created",}""")
      body should include("analytics_active_connections 2.0")
      body should include("analytics_request_duration_seconds_count")
    }
  }

  "the health route" should "not answer other paths or methods" in {
    Post("/health") ~> routesFor(MetricsRepository(pgConfig)) ~> check {
      handled shouldBe false
    }
    Get("/nope") ~> routesFor(MetricsRepository(pgConfig)) ~> check {
      handled shouldBe false
    }
  }
