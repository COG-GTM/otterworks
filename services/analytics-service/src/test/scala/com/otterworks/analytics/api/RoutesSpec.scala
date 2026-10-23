package com.otterworks.analytics.api

import akka.http.scaladsl.model.{ContentTypes, HttpEntity, StatusCodes}
import akka.http.scaladsl.model.headers.RawHeader
import akka.http.scaladsl.server.Directives.concat
import akka.http.scaladsl.testkit.ScalatestRouteTest
import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
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

class RoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(100, Millis))

  private val testConfig: PostgresConfig = PostgresConfig(
    url = "jdbc:postgresql://localhost:5432/test",
    user = "test",
    password = "test",
    maxPoolSize = 2
  )

  private def createRoutes(): (EventRoutes, AnalyticsRoutes, AnalyticsService) =
    val repo = MetricsRepository(testConfig)
    val service = AnalyticsService(repo)
    val eventRoutes = EventRoutes(service)
    val analyticsRoutes = AnalyticsRoutes(service)
    (eventRoutes, analyticsRoutes, service)

  private def caller(userId: String) = addHeader(RawHeader(EventRoutes.UserIdHeader, userId))

  private def trackJson(body: String) = HttpEntity(ContentTypes.`application/json`, body)

  // --- Event Routes ---

  "POST /api/v1/analytics/events" should "accept a valid event" in {
    val (eventRoutes, _, _) = createRoutes()
    val payload = TrackEventRequest(
      eventType = "document.created",
      userId = Some("user-1"),
      resourceId = "doc-1",
      resourceType = "document",
      metadata = Some(Map("title" -> "Test"))
    ).toJson.compactPrint
    val entity = HttpEntity(ContentTypes.`application/json`, payload)

    Post("/api/v1/analytics/events", entity) ~> caller("user-1") ~> eventRoutes.routes ~> check {
      status shouldBe StatusCodes.Accepted
      val response = responseAs[AcceptedResponse]
      response.status shouldBe "accepted"
      response.eventId should not be empty
    }
  }

  it should "work when event routes are mounted with analytics routes" in {
    val (eventRoutes, analyticsRoutes, _) = createRoutes()
    val routes = concat(eventRoutes.routes, analyticsRoutes.routes)
    val payload = TrackEventRequest(
      eventType = "document.created",
      userId = Some("user-1"),
      resourceId = "doc-1",
      resourceType = "document",
      metadata = Some(Map("title" -> "Test"))
    ).toJson.compactPrint
    val entity = HttpEntity(ContentTypes.`application/json`, payload)

    Post("/api/v1/analytics/events", entity) ~> caller("user-1") ~> routes ~> check {
      status shouldBe StatusCodes.Accepted
    }
  }

  it should "reject a request without a gateway-asserted caller" in {
    val (eventRoutes, _, service) = createRoutes()
    Post("/api/v1/analytics/events", trackJson("""{"eventType":"document.viewed","userId":"user-1","resourceId":"doc-1","resourceType":"document"}""")) ~>
      eventRoutes.routes ~> check {
        status shouldBe StatusCodes.Unauthorized
      }
    service.getEventCount.futureValue shouldBe 0
  }

  it should "reject a body userId that differs from the caller" in {
    val (eventRoutes, _, service) = createRoutes()
    Post("/api/v1/analytics/events", trackJson("""{"eventType":"document.viewed","userId":"victim","resourceId":"doc-1","resourceType":"document"}""")) ~>
      caller("attacker") ~> eventRoutes.routes ~> check {
        status shouldBe StatusCodes.Forbidden
      }
    service.getUserActivity("victim").futureValue.totalEvents shouldBe 0
  }

  it should "attribute the event to the caller when userId is omitted" in {
    val (eventRoutes, _, service) = createRoutes()
    Post("/api/v1/analytics/events", trackJson("""{"eventType":"document.viewed","resourceId":"doc-1","resourceType":"document"}""")) ~>
      caller("user-7") ~> eventRoutes.routes ~> check {
        status shouldBe StatusCodes.Accepted
      }
    service.getUserActivity("user-7").futureValue.totalEvents shouldBe 1
  }

  it should "reject event types outside EventType.All" in {
    val (eventRoutes, _, service) = createRoutes()
    Post("/api/v1/analytics/events", trackJson("""{"eventType":"admin.pwned","resourceId":"doc-1","resourceType":"document"}""")) ~>
      caller("user-1") ~> eventRoutes.routes ~> check {
        status shouldBe StatusCodes.BadRequest
      }
    service.getEventCount.futureValue shouldBe 0
  }

  it should "not let callers forge storage accounting events" in {
    val (eventRoutes, _, service) = createRoutes()
    Post("/api/v1/analytics/events", trackJson("""{"eventType":"storage.allocated","resourceId":"file-1","resourceType":"file","metadata":{"bytes":"999999999"}}""")) ~>
      caller("user-1") ~> eventRoutes.routes ~> check {
        status shouldBe StatusCodes.BadRequest
      }
    service.getStorageUsage(Some("user-1")).futureValue.totalStorageBytes shouldBe 0
  }

  it should "reject oversized metadata" in {
    val (eventRoutes, _, service) = createRoutes()
    val metadata = (1 to 17).map(i => s""""k$i":"v"""").mkString("{", ",", "}")
    Post("/api/v1/analytics/events", trackJson(s"""{"eventType":"document.viewed","resourceId":"doc-1","resourceType":"document","metadata":$metadata}""")) ~>
      caller("user-1") ~> eventRoutes.routes ~> check {
        status shouldBe StatusCodes.BadRequest
      }
    service.getEventCount.futureValue shouldBe 0
  }

  it should "reject bodies over the size limit" in {
    val (eventRoutes, _, service) = createRoutes()
    val big = "x" * (TrackEventPolicy.MaxBodyBytes.toInt + 1)
    Post("/api/v1/analytics/events", trackJson(s"""{"eventType":"document.viewed","resourceId":"doc-1","resourceType":"document","metadata":{"k":"$big"}}""")) ~>
      caller("user-1") ~> akka.http.scaladsl.server.Route.seal(eventRoutes.routes) ~> check {
        status.intValue shouldBe 413
      }
    service.getEventCount.futureValue shouldBe 0
  }

  // --- Dashboard Route ---

  "GET /api/v1/analytics/dashboard" should "return a summary with default period" in {
    val (_, analyticsRoutes, _) = createRoutes()

    Get("/api/v1/analytics/dashboard") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val summary = responseAs[DashboardSummary]
      summary.period shouldBe "7d"
      summary.totalEvents shouldBe 0
    }
  }

  it should "accept a period parameter" in {
    val (_, analyticsRoutes, _) = createRoutes()

    Get("/api/v1/analytics/dashboard?period=30d") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val summary = responseAs[DashboardSummary]
      summary.period shouldBe "30d"
    }
  }

  // --- User Activity Route ---

  "GET /api/v1/analytics/users/{id}/activity" should "return user activity" in {
    val (eventRoutes, analyticsRoutes, service) = createRoutes()

    // First track an event
    service.trackEvent("document.created", "user-42", "doc-1", "document", Map.empty).futureValue

    Get("/api/v1/analytics/users/user-42/activity") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val activity = responseAs[UserActivity]
      activity.userId shouldBe "user-42"
      activity.totalEvents shouldBe 1
    }
  }

  // --- Document Stats Route ---

  "GET /api/v1/analytics/documents/{id}/stats" should "return document stats" in {
    val (_, analyticsRoutes, service) = createRoutes()

    service.trackEvent("document.viewed", "user-1", "doc-99", "document", Map.empty).futureValue

    Get("/api/v1/analytics/documents/doc-99/stats") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val stats = responseAs[DocumentStats]
      stats.documentId shouldBe "doc-99"
      stats.views shouldBe 1
    }
  }

  // --- Top Content Route ---

  "GET /api/v1/analytics/top-content" should "return top content" in {
    val (_, analyticsRoutes, _) = createRoutes()

    Get("/api/v1/analytics/top-content?type=documents&period=7d") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val response = responseAs[TopContentResponse]
      response.contentType shouldBe "documents"
      response.period shouldBe "7d"
    }
  }

  // --- Active Users Route ---

  "GET /api/v1/analytics/active-users" should "return active users" in {
    val (_, analyticsRoutes, _) = createRoutes()

    Get("/api/v1/analytics/active-users?period=daily") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val response = responseAs[ActiveUsersResponse]
      response.period shouldBe "daily"
      response.count shouldBe 0
    }
  }

  // --- Storage Route ---

  "GET /api/v1/analytics/storage" should "return storage usage" in {
    val (_, analyticsRoutes, _) = createRoutes()

    Get("/api/v1/analytics/storage") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val response = responseAs[StorageUsageResponse]
      response.totalStorageBytes shouldBe 0
    }
  }

  it should "filter by user_id" in {
    val (_, analyticsRoutes, service) = createRoutes()

    service.trackEvent("storage.allocated", "user-1", "file-1", "file", Map("bytes" -> "512")).futureValue

    Get("/api/v1/analytics/storage?user_id=user-1") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val response = responseAs[StorageUsageResponse]
      response.userId shouldBe Some("user-1")
      response.totalStorageBytes shouldBe 512
    }
  }

  // --- Export Route ---

  "GET /api/v1/analytics/export" should "return JSON export" in {
    val (_, analyticsRoutes, service) = createRoutes()

    service.trackEvent("document.created", "user-1", "doc-1", "document", Map.empty).futureValue

    Get("/api/v1/analytics/export?format=json&period=7d") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val response = responseAs[ExportReportResponse]
      response.format shouldBe "json"
      response.recordCount shouldBe 1
    }
  }

  it should "return CSV export" in {
    val (_, analyticsRoutes, service) = createRoutes()

    service.trackEvent("document.created", "user-1", "doc-1", "document", Map.empty).futureValue

    Get("/api/v1/analytics/export?format=csv&period=7d") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`text/plain(UTF-8)`
      val csv = responseAs[String]
      csv should include("event_id,event_type,user_id,resource_id,resource_type,timestamp")
      csv should include("document.created")
    }
  }
