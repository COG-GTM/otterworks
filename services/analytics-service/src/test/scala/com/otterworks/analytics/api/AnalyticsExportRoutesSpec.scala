package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.{ContentTypes, HttpEntity, StatusCodes}
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.*
import com.otterworks.analytics.model.AnalyticsEventJsonProtocol.{*, given}
import com.otterworks.analytics.model.DashboardJsonProtocol.{*, given}
import com.otterworks.analytics.repository.MetricsRepository
import com.otterworks.analytics.service.AnalyticsService
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import spray.json.*

/** Covers the CSV rendering branches of the export endpoint and the metadata-less event payload. */
class AnalyticsExportRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(100, Millis))

  private val pgConfig = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)

  private def freshRepo(): MetricsRepository = MetricsRepository(pgConfig)

  "GET /api/v1/analytics/export?format=csv" should "return only the header row when there is no data" in {
    val routes = AnalyticsRoutes(AnalyticsService(freshRepo())).routes

    Get("/api/v1/analytics/export?format=csv") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`text/plain(UTF-8)`
      responseAs[String] shouldBe "event_id,event_type,user_id,resource_id,resource_type,timestamp\n"
    }
  }

  it should "quote fields containing commas, quotes or newlines" in {
    val repo = freshRepo()
    repo.storeEvent(
      AnalyticsEvent.create("document.created", "user,one", """say "hi"""", "doc\ntype")
    ).futureValue
    val routes = AnalyticsRoutes(AnalyticsService(repo)).routes

    Get("/api/v1/analytics/export?format=csv") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      val lines = responseAs[String].split("\n", 2)
      lines(0) shouldBe "event_id,event_type,user_id,resource_id,resource_type,timestamp"
      val row = lines(1)
      row should include(""""user,one"""")
      row should include(""""say ""hi"""""")
      row should include("\"doc\ntype\"")
    }
  }

  it should "render one CSV row per exported event" in {
    val repo = freshRepo()
    (1 to 3).foreach { i =>
      repo.storeEvent(AnalyticsEvent.create("file.uploaded", s"u$i", s"f$i", "file")).futureValue
    }
    val routes = AnalyticsRoutes(AnalyticsService(repo)).routes

    Get("/api/v1/analytics/export?format=csv&period=30d") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      val body = responseAs[String]
      body.stripLineEnd.split("\n") should have size 4
      body should include("file.uploaded")
    }
  }

  "POST /api/v1/analytics/events" should "default the metadata to an empty map when it is omitted" in {
    val repo = freshRepo()
    val service = AnalyticsService(repo)
    val payload = TrackEventRequest(
      eventType = "user.logged_in",
      userId = "user-9",
      resourceId = "session-9",
      resourceType = "session",
      metadata = None
    ).toJson.compactPrint

    Post("/api/v1/analytics/events", HttpEntity(ContentTypes.`application/json`, payload)) ~>
      EventRoutes(service).routes ~> check {
        status shouldBe StatusCodes.Accepted
        responseAs[AcceptedResponse].status shouldBe "accepted"
      }

    service.getUserActivity("user-9").futureValue.totalEvents shouldBe 1L
  }
