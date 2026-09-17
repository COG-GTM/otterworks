package com.otterworks.analytics.api

import akka.http.scaladsl.model.{ContentTypes, HttpEntity, StatusCodes}
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

/** Edge cases of the event/analytics HTTP layer: absent payload fields and CSV rendering. */
class RoutesEdgeCasesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(100, Millis))

  private val pgConfig = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)

  private def newStack(): (EventRoutes, AnalyticsRoutes, AnalyticsService) =
    val service = AnalyticsService(MetricsRepository(pgConfig))
    (EventRoutes(service), AnalyticsRoutes(service), service)

  "POST /api/v1/analytics/events" should "default the metadata when the field is absent" in {
    val (eventRoutes, analyticsRoutes, _) = newStack()
    val payload =
      """{"eventType":"file.uploaded","userId":"user-7","resourceId":"file-7","resourceType":"file"}"""

    Post("/api/v1/analytics/events", HttpEntity(ContentTypes.`application/json`, payload)) ~>
      eventRoutes.routes ~> check {
        status shouldBe StatusCodes.Accepted
        responseAs[AcceptedResponse].status shouldBe "accepted"
      }

    Get("/api/v1/analytics/top-content?type=files") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[TopContentResponse].items should have size 1
    }
  }

  "GET /api/v1/analytics/export?format=csv" should "return a header-only document when there are no events" in {
    val (_, analyticsRoutes, _) = newStack()

    Get("/api/v1/analytics/export?format=csv") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] shouldBe "event_id,event_type,user_id,resource_id,resource_type,timestamp\n"
    }
  }

  it should "quote fields containing separators or quotes" in {
    val (_, analyticsRoutes, service) = newStack()
    service.trackEvent("document.created", """user "quoted"""", "doc-1,doc-2", "document", Map.empty).futureValue

    Get("/api/v1/analytics/export?format=csv") ~> analyticsRoutes.routes ~> check {
      status shouldBe StatusCodes.OK
      val csv = responseAs[String]
      csv should include("""doc-1,doc-2""")
      csv should include(""""doc-1,doc-2"""")
      csv should include(""""user ""quoted"""""")
    }
  }
