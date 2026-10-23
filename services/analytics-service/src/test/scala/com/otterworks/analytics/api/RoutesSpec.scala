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
import com.otterworks.analytics.service.{AnalyticsService, DocumentAccess}
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import spray.json.*

import scala.concurrent.Future

class RoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(100, Millis))

  private val testConfig: PostgresConfig = PostgresConfig(
    url = "jdbc:postgresql://localhost:5432/test",
    user = "test",
    password = "test",
    maxPoolSize = 2
  )

  /** Stand-in for document-service: grants access only to the listed (user, document) pairs. */
  private final class StubDocumentAccess(readable: Set[(String, String)]) extends DocumentAccess:
    @volatile var calls: Int = 0
    def canView(caller: Caller, documentId: String): Future[Boolean] =
      calls += 1
      Future.successful(readable.contains(caller.userId -> documentId))

  private val jwtSecret = "routes-spec-secret"
  private def token(userId: String, roles: String*): String = TestJwt.sign(jwtSecret, userId, roles)
  private def bearer(userId: String, roles: String*) = RawHeader("Authorization", s"Bearer ${token(userId, roles*)}")
  private val adminHeaders = List(bearer("admin-1", "USER", "ADMIN"))
  private def userHeaders(userId: String) = List(bearer(userId, "USER"))

  private def createRoutes(
      documentAccess: DocumentAccess = StubDocumentAccess(Set("user-1" -> "doc-99"))
  ): (EventRoutes, AnalyticsRoutes, AnalyticsService) =
    val repo = MetricsRepository(testConfig)
    val service = AnalyticsService(repo)
    val eventRoutes = EventRoutes(service)
    val analyticsRoutes = AnalyticsRoutes(service, documentAccess, CallerAuth(Some(jwtSecret)))
    (eventRoutes, analyticsRoutes, service)

  // --- Event Routes ---

  "POST /api/v1/analytics/events" should "accept a valid event" in {
    val (eventRoutes, _, _) = createRoutes()
    val payload = TrackEventRequest(
      eventType = "document.created",
      userId = "user-1",
      resourceId = "doc-1",
      resourceType = "document",
      metadata = Some(Map("title" -> "Test"))
    ).toJson.compactPrint
    val entity = HttpEntity(ContentTypes.`application/json`, payload)

    Post("/api/v1/analytics/events", entity) ~> eventRoutes.routes ~> check {
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
      userId = "user-1",
      resourceId = "doc-1",
      resourceType = "document",
      metadata = Some(Map("title" -> "Test"))
    ).toJson.compactPrint
    val entity = HttpEntity(ContentTypes.`application/json`, payload)

    Post("/api/v1/analytics/events", entity) ~> routes ~> check {
      status shouldBe StatusCodes.Accepted
    }
  }

  // --- Dashboard Route ---

  "GET /api/v1/analytics/dashboard" should "return a summary with default period" in {
    val (_, analyticsRoutes, _) = createRoutes()

    Get("/api/v1/analytics/dashboard").withHeaders(adminHeaders) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val summary = responseAs[DashboardSummary]
      summary.period shouldBe "7d"
      summary.totalEvents shouldBe 0
    }
  }

  it should "accept a period parameter" in {
    val (_, analyticsRoutes, _) = createRoutes()

    Get("/api/v1/analytics/dashboard?period=30d").withHeaders(adminHeaders) ~> analyticsRoutes.routes ~> check {
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

    Get("/api/v1/analytics/users/user-42/activity").withHeaders(userHeaders("user-42")) ~> analyticsRoutes.routes ~> check {
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

    Get("/api/v1/analytics/documents/doc-99/stats").withHeaders(userHeaders("user-1")) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val stats = responseAs[DocumentStats]
      stats.documentId shouldBe "doc-99"
      stats.views shouldBe 1
    }
  }

  // --- Top Content Route ---

  "GET /api/v1/analytics/top-content" should "return top content" in {
    val (_, analyticsRoutes, _) = createRoutes()

    Get("/api/v1/analytics/top-content?type=documents&period=7d").withHeaders(adminHeaders) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val response = responseAs[TopContentResponse]
      response.contentType shouldBe "documents"
      response.period shouldBe "7d"
    }
  }

  // --- Active Users Route ---

  "GET /api/v1/analytics/active-users" should "return active users" in {
    val (_, analyticsRoutes, _) = createRoutes()

    Get("/api/v1/analytics/active-users?period=daily").withHeaders(adminHeaders) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val response = responseAs[ActiveUsersResponse]
      response.period shouldBe "daily"
      response.count shouldBe 0
    }
  }

  // --- Storage Route ---

  "GET /api/v1/analytics/storage" should "return storage usage" in {
    val (_, analyticsRoutes, _) = createRoutes()

    Get("/api/v1/analytics/storage").withHeaders(adminHeaders) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val response = responseAs[StorageUsageResponse]
      response.totalStorageBytes shouldBe 0
    }
  }

  it should "filter by user_id" in {
    val (_, analyticsRoutes, service) = createRoutes()

    service.trackEvent("storage.allocated", "user-1", "file-1", "file", Map("bytes" -> "512")).futureValue

    Get("/api/v1/analytics/storage?user_id=user-1").withHeaders(userHeaders("user-1")) ~> analyticsRoutes.routes ~> check {
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

    Get("/api/v1/analytics/export?format=json&period=7d").withHeaders(adminHeaders) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val response = responseAs[ExportReportResponse]
      response.format shouldBe "json"
      response.recordCount shouldBe 1
    }
  }

  it should "return CSV export" in {
    val (_, analyticsRoutes, service) = createRoutes()

    service.trackEvent("document.created", "user-1", "doc-1", "document", Map.empty).futureValue

    Get("/api/v1/analytics/export?format=csv&period=7d").withHeaders(adminHeaders) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`text/plain(UTF-8)`
      val csv = responseAs[String]
      csv should include("event_id,event_type,user_id,resource_id,resource_type,timestamp")
      csv should include("document.created")
    }
  }

  // --- Caller authorization ---

  private val adminOnlyPaths = Seq(
    "/api/v1/analytics/dashboard",
    "/api/v1/analytics/top-content",
    "/api/v1/analytics/active-users",
    "/api/v1/analytics/storage",
    "/api/v1/analytics/export?period=90d",
    "/api/v1/analytics/export?format=csv&period=90d",
  )

  private val allQueryPaths = adminOnlyPaths ++ Seq(
    "/api/v1/analytics/users/user-1/activity",
    "/api/v1/analytics/documents/doc-99/stats",
    "/api/v1/analytics/storage?user_id=user-1",
  )

  "Analytics query routes" should "reject requests without a valid bearer token" in {
    val (_, analyticsRoutes, _) = createRoutes()
    val forged = TestJwt.sign("wrong-secret", "admin-1", Seq("ADMIN"))
    val expired = TestJwt.sign(jwtSecret, "admin-1", Seq("ADMIN"), expiresInSeconds = -60)
    val refresh = TestJwt.sign(jwtSecret, "admin-1", Seq("ADMIN"), tokenType = "refresh")
    val unsigned = TestJwt.unsigned("admin-1", Seq("ADMIN"))
    val badHeaders: Seq[(String, List[RawHeader])] = Seq(
      "none" -> Nil,
      "header only" -> List(RawHeader("X-User-ID", "admin-1")),
      "forged" -> List(RawHeader("Authorization", s"Bearer $forged")),
      "expired" -> List(RawHeader("Authorization", s"Bearer $expired")),
      "refresh" -> List(RawHeader("Authorization", s"Bearer $refresh")),
      "alg none" -> List(RawHeader("Authorization", s"Bearer $unsigned")),
      "blank sub" -> List(bearer("  ", "ADMIN")),
      "mismatched X-User-ID" -> List(bearer("attacker", "USER"), RawHeader("X-User-ID", "user-1")),
    )
    for uri <- allQueryPaths; (label, headers) <- badHeaders do
      Get(uri).withHeaders(headers) ~> analyticsRoutes.routes ~> check {
        withClue(s"$label: $uri") { status shouldBe StatusCodes.Unauthorized }
      }
  }

  it should "accept a matching gateway X-User-ID alongside the token" in {
    val (_, analyticsRoutes, _) = createRoutes()
    Get("/api/v1/analytics/users/user-1/activity")
      .withHeaders(bearer("user-1", "USER"), RawHeader("X-User-ID", "user-1")) ~> analyticsRoutes.routes ~> check {
        status shouldBe StatusCodes.OK
      }
  }

  it should "reject every query when no JWT secret is configured" in {
    val service = AnalyticsService(MetricsRepository(testConfig))
    val routes = AnalyticsRoutes(service, StubDocumentAccess(Set.empty), CallerAuth(None)).routes
    val headerSets = Seq(
      List(RawHeader("X-User-ID", "user-1")),
      List(bearer("user-1", "USER")),
      List(RawHeader("X-User-ID", "admin-1"), bearer("admin-1", "ADMIN")),
    )
    for uri <- allQueryPaths; headers <- headerSets do
      Get(uri).withHeaders(headers) ~> routes ~> check {
        withClue(uri) { status shouldBe StatusCodes.Unauthorized }
      }
  }

  it should "ignore a client-supplied X-User-Roles header" in {
    val (_, analyticsRoutes, _) = createRoutes()
    Get("/api/v1/analytics/export").withHeaders(bearer("attacker", "USER"), RawHeader("X-User-Roles", "ADMIN")) ~>
      analyticsRoutes.routes ~> check {
        status shouldBe StatusCodes.Forbidden
      }
  }

  it should "reserve cross-user aggregates and exports for admins" in {
    val (_, analyticsRoutes, service) = createRoutes()
    service.trackEvent("document.created", "victim", "doc-1", "document", Map.empty).futureValue
    adminOnlyPaths.foreach { uri =>
      Get(uri).withHeaders(userHeaders("attacker")) ~> analyticsRoutes.routes ~> check {
        withClue(uri) { status shouldBe StatusCodes.Forbidden }
        responseAs[String] should not include "victim"
      }
    }
  }

  it should "accept ADMIN and OWNER roles case-insensitively" in {
    val (_, analyticsRoutes, _) = createRoutes()
    Seq(Seq("ADMIN"), Seq("admin"), Seq("USER", "Owner")).foreach { roles =>
      Get("/api/v1/analytics/dashboard").withHeaders(bearer("a", roles*)) ~>
        analyticsRoutes.routes ~> check {
          withClue(roles) { status shouldBe StatusCodes.OK }
        }
    }
  }

  it should "not treat EDITOR as an admin role" in {
    val (_, analyticsRoutes, _) = createRoutes()
    Get("/api/v1/analytics/export").withHeaders(bearer("e", "USER", "EDITOR")) ~>
      analyticsRoutes.routes ~> check {
        status shouldBe StatusCodes.Forbidden
      }
  }

  "GET /api/v1/analytics/users/{id}/activity" should "forbid reading another user's activity" in {
    val (_, analyticsRoutes, service) = createRoutes()
    service.trackEvent("document.created", "victim", "doc-secret", "document", Map.empty).futureValue

    Get("/api/v1/analytics/users/victim/activity").withHeaders(userHeaders("attacker")) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.Forbidden
      responseAs[String] should not include "doc-secret"
    }
  }

  it should "let an admin read any user's activity" in {
    val (_, analyticsRoutes, service) = createRoutes()
    service.trackEvent("document.created", "victim", "doc-1", "document", Map.empty).futureValue

    Get("/api/v1/analytics/users/victim/activity").withHeaders(adminHeaders) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[UserActivity].totalEvents shouldBe 1
    }
  }

  "GET /api/v1/analytics/storage" should "forbid filtering by another user's id" in {
    val (_, analyticsRoutes, _) = createRoutes()
    Get("/api/v1/analytics/storage?user_id=victim").withHeaders(userHeaders("attacker")) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.Forbidden
    }
  }

  it should "let an admin filter by any user's id" in {
    val (_, analyticsRoutes, service) = createRoutes()
    service.trackEvent("storage.allocated", "victim", "file-1", "file", Map("bytes" -> "64")).futureValue
    Get("/api/v1/analytics/storage?user_id=victim").withHeaders(adminHeaders) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[StorageUsageResponse].totalStorageBytes shouldBe 64
    }
  }

  "GET /api/v1/analytics/documents/{id}/stats" should "forbid callers document-service does not let read the document" in {
    val access = StubDocumentAccess(Set("owner" -> "doc-99"))
    val (_, analyticsRoutes, service) = createRoutes(access)
    service.trackEvent("document.viewed", "owner", "doc-99", "document", Map.empty).futureValue

    Get("/api/v1/analytics/documents/doc-99/stats").withHeaders(userHeaders("attacker")) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.Forbidden
    }
    access.calls shouldBe 1
  }

  it should "let an admin read stats without a document-service lookup" in {
    val access = StubDocumentAccess(Set.empty)
    val (_, analyticsRoutes, _) = createRoutes(access)

    Get("/api/v1/analytics/documents/doc-99/stats").withHeaders(adminHeaders) ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
    }
    access.calls shouldBe 0
  }
