package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.{ContentTypes, HttpEntity, StatusCodes}
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.*
import com.otterworks.analytics.model.AnalyticsEventJsonProtocol.{*, given}
import com.otterworks.analytics.repository.MetricsRepository
import com.otterworks.analytics.service.AnalyticsService
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import spray.json.*

/** CSV rendering edge cases of GET /export, plus event ingestion without metadata. */
class ExportRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(50, Millis))

  private val pgConfig = PostgresConfig(
    url = "jdbc:postgresql://localhost:5432/test",
    user = "test",
    password = "test",
    maxPoolSize = 2
  )

  private def createService(): AnalyticsService = AnalyticsService(MetricsRepository(pgConfig))

  private val csvHeader = "event_id,event_type,user_id,resource_id,resource_type,timestamp"

  "GET /export?format=csv" should "return a header-only document when there is no data" in {
    val routes = AnalyticsRoutes(createService()).routes

    Get("/api/v1/analytics/export?format=csv") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] shouldBe s"$csvHeader\n"
    }
  }

  it should "quote fields containing commas, quotes or newlines" in {
    val service = createService()
    service.trackEvent("document.created", "user-1", """doc,1 "primary"""", "document", Map.empty).futureValue
    val routes = AnalyticsRoutes(service).routes

    Get("/api/v1/analytics/export?format=csv") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      val lines = responseAs[String].linesIterator.toList
      lines.head shouldBe csvHeader
      lines(1) should include(""""doc,1 ""primary"""""")
      lines should have size 2
    }
  }

  it should "leave fields without separators unquoted" in {
    val service = createService()
    service.trackEvent("file.uploaded", "user-2", "file-1", "file", Map.empty).futureValue
    val routes = AnalyticsRoutes(service).routes

    Get("/api/v1/analytics/export?format=csv") ~> routes ~> check {
      val row = responseAs[String].linesIterator.toList(1)
      row should include(",file.uploaded,user-2,file-1,file,")
      row should not include "\""
    }
  }

  "POST /events" should "default the metadata to an empty map when it is omitted" in {
    val service = createService()
    val routes = EventRoutes(service).routes
    val payload = """{"eventType":"user.logged_in","userId":"user-9","resourceId":"session-1","resourceType":"session"}"""

    Post("/api/v1/analytics/events", HttpEntity(ContentTypes.`application/json`, payload)) ~> routes ~> check {
      status shouldBe StatusCodes.Accepted
      responseAs[AcceptedResponse].status shouldBe "accepted"
    }

    val activity = service.getUserActivity("user-9").futureValue
    activity.totalEvents shouldBe 1L
  }
