package com.otterworks.analytics.api

import akka.http.scaladsl.model.{ContentTypes, HttpEntity, StatusCodes}
import akka.http.scaladsl.server.Route
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.EventType
import com.otterworks.analytics.repository.MetricsRepository
import com.otterworks.analytics.service.AnalyticsService
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

/** Ingest endpoint contract: optional metadata and rejection of malformed payloads. */
class EventRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(50, Millis))

  private val pgConfig = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)

  private def post(payload: String) =
    Post("/api/v1/analytics/events").withEntity(HttpEntity(ContentTypes.`application/json`, payload))

  "POST /api/v1/analytics/events" should "default the metadata to empty when it is omitted" in {
    val repo = MetricsRepository(pgConfig)
    val routes = EventRoutes(AnalyticsService(repo)).routes
    val payload =
      s"""{"eventType":"${EventType.FileUploaded}","userId":"u-1","resourceId":"f-1","resourceType":"file"}"""

    post(payload) ~> routes ~> check {
      status shouldBe StatusCodes.Accepted
      responseAs[String] should include(""""status":"accepted"""")
    }

    repo.getEventCount.futureValue shouldBe 1L
    val activity = repo.getUserActivity("u-1").futureValue
    activity.filesUploaded shouldBe 1L
    activity.recentEvents.map(_.resourceId) shouldBe List("f-1")
  }

  it should "reject a payload that is missing a required field" in {
    val routes = EventRoutes(AnalyticsService(MetricsRepository(pgConfig))).routes
    post("""{"userId":"u-1"}""") ~> Route.seal(routes) ~> check {
      status shouldBe StatusCodes.BadRequest
      responseAs[String] should include("eventType")
    }
  }
