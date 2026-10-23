package com.otterworks.analytics.qa

import akka.http.scaladsl.model.{ContentTypes, HttpEntity, StatusCodes}
import akka.http.scaladsl.server.Directives.concat
import akka.http.scaladsl.server.Route
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.api.{AnalyticsRoutes, EventRoutes}
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.repository.InMemoryMetricsRepository
import com.otterworks.analytics.service.AnalyticsService
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

/**
 * QA audit (docs/qa/analytics-report.md): HTTP contract of /api/v1/analytics.
 * Tests wrapped in `pendingUntilFixed` document findings ANL-x; they report as
 * pending while the defect exists and fail once it is fixed (remove the wrapper then).
 */
class QaAnalyticsRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest:

  private val cfg = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)

  private def routes(): Route =
    val service = AnalyticsService(new InMemoryMetricsRepository(cfg))
    Route.seal(concat(EventRoutes(service).routes, AnalyticsRoutes(service).routes))

  private def event(
      eventType: String = "document.created",
      userId: String = "user-1",
      resourceId: String = "doc-1",
      resourceType: String = "document",
      extra: Map[String, JsValue] = Map.empty
  ): HttpEntity.Strict =
    val fields = Map[String, JsValue](
      "eventType" -> JsString(eventType),
      "userId" -> JsString(userId),
      "resourceId" -> JsString(resourceId),
      "resourceType" -> JsString(resourceType)
    ) ++ extra
    HttpEntity(ContentTypes.`application/json`, JsObject(fields).compactPrint)

  private def json(body: String): JsObject = body.parseJson.asJsObject
  private def num(o: JsObject, field: String): BigDecimal = o.fields(field).asInstanceOf[JsNumber].value

  "POST /events" should "reflect ingested events in dashboard, user activity and document stats" in {
    val r = routes()
    Post("/api/v1/analytics/events", event()) ~> r ~> check { status shouldBe StatusCodes.Accepted }
    Post("/api/v1/analytics/events", event("document.viewed", userId = "user-2")) ~> r ~> check {
      status shouldBe StatusCodes.Accepted
    }
    Get("/api/v1/analytics/dashboard?period=7d") ~> r ~> check {
      val o = json(responseAs[String])
      num(o, "totalEvents") shouldBe 2
      num(o, "documentsCreated") shouldBe 1
    }
    Get("/api/v1/analytics/users/user-1/activity") ~> r ~> check {
      num(json(responseAs[String]), "totalEvents") shouldBe 1
    }
    Get("/api/v1/analytics/documents/doc-1/stats") ~> r ~> check {
      val o = json(responseAs[String])
      num(o, "views") shouldBe 1
      num(o, "uniqueViewers") shouldBe 1
    }
  }

  it should "accept and persist optional metadata" in {
    val r = routes()
    val meta = Map("metadata" -> JsObject("bytes" -> JsString("2048")))
    Post("/api/v1/analytics/events", event("storage.allocated", extra = meta)) ~> r ~> check {
      status shouldBe StatusCodes.Accepted
    }
    Get("/api/v1/analytics/storage?user_id=user-1") ~> r ~> check {
      num(json(responseAs[String]), "totalStorageBytes") shouldBe 2048
    }
  }

  it should "reject a body missing required fields with 400" in {
    val body = HttpEntity(ContentTypes.`application/json`, """{"eventType":"document.created"}""")
    Post("/api/v1/analytics/events", body) ~> routes() ~> check { status shouldBe StatusCodes.BadRequest }
  }

  it should "reject malformed JSON with 400" in {
    val body = HttpEntity(ContentTypes.`application/json`, "{not json")
    Post("/api/v1/analytics/events", body) ~> routes() ~> check { status shouldBe StatusCodes.BadRequest }
  }

  it should "reject unsupported HTTP methods with 405" in {
    Get("/api/v1/analytics/events") ~> routes() ~> check { status shouldBe StatusCodes.MethodNotAllowed }
  }

  it should "reject event types outside EventType.All (finding ANL-1)" in pendingUntilFixed {
    Post("/api/v1/analytics/events", event("totally.made_up")) ~> routes() ~> check {
      status shouldBe StatusCodes.BadRequest
    }
  }

  it should "reject blank userId/resourceId (finding ANL-2)" in pendingUntilFixed {
    Post("/api/v1/analytics/events", event(userId = "", resourceId = "")) ~> routes() ~> check {
      status shouldBe StatusCodes.BadRequest
    }
  }

  "GET /dashboard" should "default to the 7d period" in {
    Get("/api/v1/analytics/dashboard") ~> routes() ~> check {
      status shouldBe StatusCodes.OK
      json(responseAs[String]).fields("period") shouldBe JsString("7d")
    }
  }

  it should "reject an unknown period instead of silently using 7d (finding ANL-3)" in pendingUntilFixed {
    Get("/api/v1/analytics/dashboard?period=last-century") ~> routes() ~> check {
      status shouldBe StatusCodes.BadRequest
    }
  }

  "GET /top-content" should "reject a non-numeric limit with 400" in {
    Get("/api/v1/analytics/top-content?limit=abc") ~> routes() ~> check {
      status shouldBe StatusCodes.BadRequest
    }
  }

  it should "reject a negative limit (finding ANL-4)" in pendingUntilFixed {
    Get("/api/v1/analytics/top-content?limit=-5") ~> routes() ~> check {
      status shouldBe StatusCodes.BadRequest
    }
  }

  "GET /active-users" should "default to the daily period" in {
    Get("/api/v1/analytics/active-users") ~> routes() ~> check {
      json(responseAs[String]).fields("period") shouldBe JsString("daily")
    }
  }

  "GET /export" should "return a header-only CSV when there is no data" in {
    Get("/api/v1/analytics/export?format=csv") ~> routes() ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] shouldBe "event_id,event_type,user_id,resource_id,resource_type,timestamp\n"
    }
  }

  it should "RFC-4180 escape commas and quotes in CSV fields" in {
    val r = routes()
    Post("/api/v1/analytics/events", event(userId = "a,b", resourceId = "say \"hi\"")) ~> r ~> check {
      status shouldBe StatusCodes.Accepted
    }
    Get("/api/v1/analytics/export?format=csv") ~> r ~> check {
      val row = responseAs[String].split("\n")(1)
      row should include("\"a,b\"")
      row should include("\"say \"\"hi\"\"\"")
    }
  }

  it should "return JSON export with record count by default" in {
    val r = routes()
    Post("/api/v1/analytics/events", event()) ~> r ~> check { status shouldBe StatusCodes.Accepted }
    Get("/api/v1/analytics/export?period=30d") ~> r ~> check {
      val o = json(responseAs[String])
      o.fields("format") shouldBe JsString("json")
      num(o, "recordCount") shouldBe 1
    }
  }

  it should "reject an unsupported export format (finding ANL-5)" in pendingUntilFixed {
    Get("/api/v1/analytics/export?format=xml") ~> routes() ~> check {
      status shouldBe StatusCodes.BadRequest
    }
  }

  "GET unknown analytics path" should "return 404" in {
    Get("/api/v1/analytics/nope") ~> routes() ~> check { status shouldBe StatusCodes.NotFound }
  }
