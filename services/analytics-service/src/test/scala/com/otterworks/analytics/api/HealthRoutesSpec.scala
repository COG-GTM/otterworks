package com.otterworks.analytics.api

import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.MetricsRepository
import com.otterworks.analytics.service.AnalyticsService
import io.prometheus.client.CollectorRegistry
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import scala.concurrent.Future

/** Covers GET /health (healthy + degraded) and the Prometheus GET /metrics endpoint. */
class HealthRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(50, Millis))

  private val pgConfig = PostgresConfig(
    url = "jdbc:postgresql://localhost:5432/test",
    user = "test",
    password = "test",
    maxPoolSize = 2
  )

  /** A repository whose reads always fail, standing in for an unreachable store. */
  private class FailingRepository extends MetricsRepository:
    private def boom[A]: Future[A] = Future.failed(new RuntimeException("metrics store unreachable"))
    def storeEvent(event: AnalyticsEvent): Future[Unit] = boom
    def getDashboardSummary(period: String): Future[DashboardSummary] = boom
    def getUserActivity(userId: String): Future[UserActivity] = boom
    def getDocumentStats(documentId: String): Future[DocumentStats] = boom
    def getTopContent(contentType: String, period: String, limit: Int): Future[TopContentResponse] = boom
    def getActiveUsers(period: String): Future[ActiveUsersResponse] = boom
    def getStorageUsage(userId: Option[String]): Future[StorageUsageResponse] = boom
    def getExportData(period: String): Future[List[Map[String, String]]] = boom
    def getEventCount: Future[Long] = boom

  "GET /health" should "report healthy with the number of processed events" in {
    val service = AnalyticsService(MetricsRepository(pgConfig))
    service.trackEvent(EventType.DocumentCreated, "user-1", "doc-1", "document", Map.empty).futureValue
    service.trackEvent(EventType.FileUploaded, "user-1", "file-1", "file", Map.empty).futureValue
    val routes = HealthRoutes(service).routes

    Get("/health") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      val body = responseAs[String]
      body should include(""""status":"healthy"""")
      body should include(""""service":"analytics-service"""")
      body should include(""""eventsProcessed":2""")
    }
  }

  it should "report degraded with 503 when the metrics store is unavailable" in {
    val routes = HealthRoutes(AnalyticsService(new FailingRepository)).routes

    Get("/health") ~> routes ~> check {
      status shouldBe StatusCodes.ServiceUnavailable
      val body = responseAs[String]
      body should include(""""status":"degraded"""")
      body should include(""""eventsProcessed":0""")
    }
  }

  "GET /metrics" should "expose the service's Prometheus collectors in text format" in {
    HealthRoutes.eventsReceivedTotal.labels(EventType.DocumentCreated).inc()
    HealthRoutes.requestDuration.labels("GET", "/health", "200").observe(0.25)
    HealthRoutes.activeConnections.inc()

    val routes = HealthRoutes(AnalyticsService(MetricsRepository(pgConfig))).routes

    Get("/metrics") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      val body = responseAs[String]
      body should include("analytics_events_received_total")
      body should include("analytics_request_duration_seconds_count")
      body should include("analytics_active_connections")

      val registry = CollectorRegistry.defaultRegistry
      registry.getSampleValue(
        "analytics_events_received_total",
        Array("event_type"),
        Array(EventType.DocumentCreated)
      ) shouldBe 1.0
      registry.getSampleValue(
        "analytics_request_duration_seconds_count",
        Array("method", "path", "status"),
        Array("GET", "/health", "200")
      ) shouldBe 1.0
      registry.getSampleValue("analytics_active_connections") shouldBe 1.0
    }
  }
