package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.{ContentTypes, StatusCodes}
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.db.AnalyticsDb
import com.otterworks.analytics.model.*
import com.otterworks.analytics.model.MarketJsonProtocol.{*, given}
import com.otterworks.analytics.repository.MarketRepository
import com.otterworks.analytics.service.MarginService
import org.scalatest.BeforeAndAfterAll
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import scala.concurrent.Future

/**
 * Exercises the margin export rendering (CSV vs JSON) with a stubbed dashboard, so the
 * formatting branches are covered without a PostgreSQL container.
 */
class MarginRoutesExportSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with BeforeAndAfterAll:

  private val db = new AnalyticsDb(PostgresConfig("jdbc:postgresql://localhost:5432/unused", "u", "p", 1))
  private val repo = new MarketRepository(db)

  override def afterAll(): Unit =
    db.close()
    super.afterAll()

  private val rows = List(
    MarginRow("SKU-1", "Salmon fillet, 1kg", "Seafood", "Nordic AS",
      BigDecimal(20), BigDecimal(8), BigDecimal(1), BigDecimal(2), BigDecimal(11), BigDecimal(45)),
    MarginRow("SKU-2", """Cod "premium"""", "Seafood", "Nordic AS",
      BigDecimal(30), BigDecimal(12), BigDecimal(2), BigDecimal(3), BigDecimal(17), BigDecimal(43.3333))
  )

  private val dashboard = MarginsResponse(
    asOfDate = "2024-03-01",
    source = "seed",
    lastSyncAt = Some("2024-03-01T00:00:00Z"),
    kpis = MarginKpis(BigDecimal(44), BigDecimal(14), BigDecimal(95), BigDecimal(3000)),
    rows = rows
  )

  private class StubMarginService extends MarginService(repo):
    override def marginsDashboard(): Future[MarginsResponse] = Future.successful(dashboard)

  private val routes = MarginRoutes(StubMarginService(), repo).routes

  "GET /api/v1/analytics/margins/export?format=csv" should "render the grid as CSV with quoted fields" in {
    Get("/api/v1/analytics/margins/export?format=csv") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`text/plain(UTF-8)`
      val lines = responseAs[String].stripLineEnd.split("\n")
      lines should have size 3
      lines(0) shouldBe
        "sku,name,category,supplier,list_price_usd,commodity_cost_usd,freight_cost_usd,overhead_cost_usd,cogs_usd,margin_pct"
      lines(1) shouldBe "SKU-1,\"Salmon fillet, 1kg\",Seafood,Nordic AS,20,8,1,2,11,45"
      lines(2) shouldBe "SKU-2,\"Cod \"\"premium\"\"\",Seafood,Nordic AS,30,12,2,3,17,43.3333"
    }
  }

  "GET /api/v1/analytics/margins/export" should "default to the JSON dashboard payload" in {
    Get("/api/v1/analytics/margins/export") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      val response = responseAs[MarginsResponse]
      response.asOfDate shouldBe "2024-03-01"
      response.rows.map(_.sku) shouldBe List("SKU-1", "SKU-2")
    }
  }

  it should "treat an unknown format as JSON" in {
    Get("/api/v1/analytics/margins/export?format=xml") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[MarginsResponse].kpis.grossMarginPct shouldBe BigDecimal(44)
    }
  }

  "GET /api/v1/analytics/margins" should "serve the dashboard payload" in {
    Get("/api/v1/analytics/margins") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[MarginsResponse].source shouldBe "seed"
    }
  }
