package com.otterworks.analytics.api

import akka.http.scaladsl.model.{ContentTypes, StatusCodes}
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.MetricsRepository
import com.otterworks.analytics.service.AnalyticsService
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.concurrent.ScalaFutures.convertScalaFuture
import spray.json.*

import scala.concurrent.Future

class HealthRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest:

  private val cfg = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)

  private object FailingRepository extends MetricsRepository:
    private def boom[T]: Future[T] = Future.failed(new RuntimeException("store down"))
    def storeEvent(event: AnalyticsEvent): Future[Unit] = boom
    def getDashboardSummary(period: String): Future[DashboardSummary] = boom
    def getUserActivity(userId: String): Future[UserActivity] = boom
    def getDocumentStats(documentId: String): Future[DocumentStats] = boom
    def getTopContent(contentType: String, period: String, limit: Int): Future[TopContentResponse] = boom
    def getActiveUsers(period: String): Future[ActiveUsersResponse] = boom
    def getStorageUsage(userId: Option[String]): Future[StorageUsageResponse] = boom
    def getExportData(period: String): Future[List[Map[String, String]]] = boom
    def getEventCount: Future[Long] = boom

  "GET /health" should "report healthy with the processed event count" in {
    val service = AnalyticsService(MetricsRepository(cfg))
    service.trackEvent("document.created", "u1", "d1", "document", Map.empty).futureValue
    service.trackEvent("file.uploaded", "u1", "f1", "file", Map.empty).futureValue

    Get("/health") ~> HealthRoutes(service).routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`application/json`
      val body = responseAs[String].parseJson.asJsObject.fields
      body("status") shouldBe JsString("healthy")
      body("service") shouldBe JsString("analytics-service")
      body("eventsProcessed") shouldBe JsNumber(2)
    }
  }

  it should "report degraded with 503 when the event store fails" in {
    val service = AnalyticsService(FailingRepository)

    Get("/health") ~> HealthRoutes(service).routes ~> check {
      status shouldBe StatusCodes.ServiceUnavailable
      val body = responseAs[String].parseJson.asJsObject.fields
      body("status") shouldBe JsString("degraded")
      body("eventsProcessed") shouldBe JsNumber(0)
    }
  }

  "GET /metrics" should "expose the service's Prometheus metrics in text format" in {
    HealthRoutes.eventsReceivedTotal.labels("document.created").inc()
    HealthRoutes.requestDuration.labels("GET", "/health", "200").observe(0.01)
    HealthRoutes.activeConnections.set(3)
    val service = AnalyticsService(MetricsRepository(cfg))

    Get("/metrics") ~> HealthRoutes(service).routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`text/plain(UTF-8)`
      val text = responseAs[String]
      text should include("analytics_events_received_total{event_type=\"document.created\",}")
      text should include("analytics_request_duration_seconds_bucket")
      text should include("analytics_active_connections 3.0")
    }
  }

  "HealthRoutes" should "not handle unrelated paths" in {
    val service = AnalyticsService(MetricsRepository(cfg))
    Get("/healthz") ~> HealthRoutes(service).routes ~> check {
      handled shouldBe false
    }
  }
