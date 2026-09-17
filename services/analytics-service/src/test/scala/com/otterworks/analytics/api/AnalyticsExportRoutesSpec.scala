package com.otterworks.analytics.api

import akka.http.scaladsl.model.{ContentTypes, StatusCodes}
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.EventType
import com.otterworks.analytics.repository.MetricsRepository
import com.otterworks.analytics.service.AnalyticsService
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import scala.concurrent.Future

/** CSV rendering of GET /api/v1/analytics/export, including field escaping. */
class AnalyticsExportRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(50, Millis))

  private val pgConfig = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)

  private def routesWith(events: (String, String)*): AnalyticsRoutes =
    val service = AnalyticsService(MetricsRepository(pgConfig))
    Future
      .sequence(events.toList.map { case (eventType, resourceId) =>
        service.trackEvent(eventType, "u1", resourceId, "document", Map.empty)
      })
      .futureValue
    AnalyticsRoutes(service)

  "GET /export?format=csv" should "render a header-only CSV when there is nothing to export" in {
    Get("/api/v1/analytics/export?format=csv") ~> routesWith().routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`text/plain(UTF-8)`
      responseAs[String] shouldBe "event_id,event_type,user_id,resource_id,resource_type,timestamp\n"
    }
  }

  it should "render one row per event in the declared column order" in {
    Get("/api/v1/analytics/export?format=csv") ~> routesWith((EventType.DocumentViewed, "doc-1")).routes ~> check {
      status shouldBe StatusCodes.OK
      val lines = responseAs[String].split("\n").toList
      lines should have size 2
      lines.head shouldBe "event_id,event_type,user_id,resource_id,resource_type,timestamp"
      val cells = lines(1).split(",").toList
      cells(1) shouldBe EventType.DocumentViewed
      cells(2) shouldBe "u1"
      cells(3) shouldBe "doc-1"
      cells(4) shouldBe "document"
    }
  }

  it should "quote and escape fields containing commas or quotes" in {
    val routes = routesWith((EventType.DocumentViewed, """doc,with"quote""")).routes
    Get("/api/v1/analytics/export?format=csv") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] should include(""""doc,with""quote"""")
    }
  }

  "GET /export" should "default to the JSON report" in {
    Get("/api/v1/analytics/export") ~> routesWith((EventType.FileUploaded, "file-1")).routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`application/json`
      val body = responseAs[String]
      body should include(""""format":"json"""")
      body should include(""""recordCount":1""")
    }
  }

  it should "ignore an unsupported format and fall back to JSON" in {
    Get("/api/v1/analytics/export?format=parquet") ~> routesWith().routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] should include(""""format":"json"""")
    }
  }
