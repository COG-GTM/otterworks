package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.{ContentTypes, HttpEntity, StatusCodes}
import akka.http.scaladsl.model.headers.RawHeader
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.model.*
import com.otterworks.analytics.model.MarketJsonProtocol.{*, given}
import com.otterworks.analytics.repository.MarketRepository
import com.otterworks.analytics.service.MarginService
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

import java.util.concurrent.atomic.AtomicInteger
import scala.concurrent.Future

/** Role enforcement on POST /api/v1/analytics/market/observations (no database needed). */
class MarketIngestAuthSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest:

  private final class RecordingMarginService extends MarginService(null.asInstanceOf[MarketRepository]):
    val calls = new AtomicInteger(0)
    override def ingest(request: ObservationsRequest): Future[Either[List[RejectedObservation], ObservationsResponse]] =
      calls.incrementAndGet()
      Future.successful(Right(ObservationsResponse(request.observations.size, Nil, 40, 7L)))

  private val body = HttpEntity(
    ContentTypes.`application/json`,
    ObservationsRequest(List(Observation("SALMON_NOK_KG", "2025-01-02", BigDecimal("1.00"))), None).toJson.compactPrint
  )

  private def post(headers: (String, String)*) =
    Post("/api/v1/analytics/market/observations", body).withHeaders(headers.map((k, v) => RawHeader(k, v)).toList)

  private def setup() =
    val svc = new RecordingMarginService
    (svc, MarketIngestRoutes(svc, null.asInstanceOf[MarketRepository]).routes)

  "POST /market/observations" should "refuse a signed-in user without an operator role" in {
    val (svc, routes) = setup()
    post("X-User-ID" -> "mallory", "X-User-Roles" -> "USER") ~> routes ~> check {
      status shouldBe StatusCodes.Forbidden
    }
    post("X-User-ID" -> "mallory", "X-User-Roles" -> "USER,EDITOR") ~> routes ~> check {
      status shouldBe StatusCodes.Forbidden
    }
    post("X-User-ID" -> "mallory") ~> routes ~> check {
      status shouldBe StatusCodes.Forbidden
    }
    svc.calls.get shouldBe 0
  }

  it should "require a forwarded identity" in {
    val (svc, routes) = setup()
    post("X-User-Roles" -> "ADMIN") ~> routes ~> check {
      status shouldBe StatusCodes.Unauthorized
    }
    post() ~> routes ~> check {
      status shouldBe StatusCodes.Unauthorized
    }
    svc.calls.get shouldBe 0
  }

  it should "accept ADMIN and OWNER callers" in {
    val (svc, routes) = setup()
    post("X-User-ID" -> "alice", "X-User-Roles" -> "USER,ADMIN") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[ObservationsResponse].accepted shouldBe 1
    }
    post("X-User-ID" -> "owner", "X-User-Roles" -> "owner") ~> routes ~> check {
      status shouldBe StatusCodes.OK
    }
    svc.calls.get shouldBe 2
  }
