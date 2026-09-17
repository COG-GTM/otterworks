package com.otterworks.analytics.api

import akka.http.scaladsl.model.{ContentTypes, StatusCodes}
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.db.AnalyticsDb
import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.MarketRepository
import com.otterworks.analytics.service.MarginService
import org.scalatest.BeforeAndAfterAll
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import scala.concurrent.{ExecutionContext, Future}

/**
 * Margin query routes against an in-memory stand-in for the market repository: the
 * grid, the series filters and both export formats, with no database involved.
 */
class MarginRoutesSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest with BeforeAndAfterAll:

  // Slick opens connections lazily and every query method below is overridden, so this
  // handle never dials PostgreSQL.
  private val idleDb = new AnalyticsDb(PostgresConfig("jdbc:postgresql://localhost:5432/none", "u", "p", 1))

  override def afterAll(): Unit =
    idleDb.close()
    super.afterAll()

  private val rows = List(
    MarginRow(
      sku = "SLM-001", name = "Salmon Fillet, skin-on", category = "Seafood", supplier = "NordicCatch AS",
      listPriceUsd = BigDecimal("30.00"), commodityCostUsd = BigDecimal("10.0000"),
      freightCostUsd = BigDecimal("0.1200"), overheadCostUsd = BigDecimal("1.5180"),
      cogsUsd = BigDecimal("11.6380"), marginPct = BigDecimal("61.2067")
    ),
    MarginRow(
      sku = "SGR-002", name = "Cane Sugar 1kg", category = "Grocery", supplier = "Acme",
      listPriceUsd = BigDecimal("4.00"), commodityCostUsd = BigDecimal("1.0000"),
      freightCostUsd = BigDecimal("0.1000"), overheadCostUsd = BigDecimal("0.1100"),
      cogsUsd = BigDecimal("1.2100"), marginPct = BigDecimal("69.7500")
    )
  )

  private val fakeStatus = MarketStatus(
    source = "manual_pull",
    lastRunType = Some("manual_pull"),
    lastCompletedAt = Some("2024-03-01T00:00:00Z"),
    observationsCount = 3L,
    asOfDate = Some("2024-03-01")
  )

  private class FakeMarketRepository(using ec: ExecutionContext) extends MarketRepository(idleDb):
    override def marginRowsLatest(): Future[Seq[MarginRow]] = Future.successful(rows)
    override def marketStatus(): Future[MarketStatus] = Future.successful(fakeStatus)
    override def listPrices(seriesCode: String, from: Option[String], to: Option[String]): Future[Seq[PricePoint]] =
      val value = if seriesCode == MarginService.SalmonSeriesCode then BigDecimal("101.25") else BigDecimal("2500.00")
      Future.successful(Seq(PricePoint(seriesCode, "2024-03-01", value, "manual_pull")))
    override def marginSeries(
        sku: Option[String],
        category: Option[String],
        from: Option[String],
        to: Option[String]
    ): Future[Seq[MarginSeriesPoint]] =
      val point = (sku, category) match
        case (Some(_), _)    => MarginSeriesPoint("2024-03-01", BigDecimal("61.2067"))
        case (None, Some(_)) => MarginSeriesPoint("2024-03-01", BigDecimal("65.4784"))
        case (None, None)    => MarginSeriesPoint("2024-03-01", BigDecimal("65.4784"))
      Future.successful(Seq(point))

  /** A market that has never been synced: no rows, no prices, no as-of date. */
  private class EmptyMarketRepository(using ec: ExecutionContext) extends MarketRepository(idleDb):
    override def marginRowsLatest(): Future[Seq[MarginRow]] = Future.successful(Seq.empty)
    override def marketStatus(): Future[MarketStatus] = Future.successful(
      MarketStatus(source = "seed", lastRunType = None, lastCompletedAt = None, observationsCount = 0L, asOfDate = None)
    )
    override def listPrices(seriesCode: String, from: Option[String], to: Option[String]): Future[Seq[PricePoint]] =
      Future.successful(Seq.empty)

  private def routes =
    val repo = new FakeMarketRepository
    MarginRoutes(new MarginService(repo), repo).routes

  "GET /api/v1/analytics/margins" should "return the KPI block and every grid row" in {
    Get("/api/v1/analytics/margins") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      val body = responseAs[String]
      body should include(""""as_of_date":"2024-03-01"""")
      body should include(""""source":"manual_pull"""")
      // KPIs are the mean of the two rows: (61.2067 + 69.75)/2 and (11.638 + 1.21)/2.
      body should include(""""gross_margin_pct":65.48""")
      body should include(""""avg_cogs_usd":6.42""")
      body should include(""""salmon_index":101.25""")
      body should include(""""freight_index":2500.00""")
      body should include(""""sku":"SLM-001"""")
      body should include(""""sku":"SGR-002"""")
    }
  }

  it should "return zeroed KPIs and an empty grid before the first sync" in {
    val repo = new EmptyMarketRepository
    Get("/api/v1/analytics/margins") ~> MarginRoutes(new MarginService(repo), repo).routes ~> check {
      status shouldBe StatusCodes.OK
      val body = responseAs[String]
      body should include(""""as_of_date":""""")
      body should include(""""gross_margin_pct":0.00""")
      body should include(""""avg_cogs_usd":0.00""")
      body should include(""""salmon_index":0.00""")
      body should include(""""freight_index":0.00""")
      body should include(""""rows":[]""")
    }
  }

  "GET /margins/series" should "pass the sku, category and date filters through" in {
    Get("/api/v1/analytics/margins/series?sku=SLM-001&from=2024-01-01&to=2024-03-31") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      val body = responseAs[String]
      body should include(""""sku":"SLM-001"""")
      body should include(""""margin_pct":61.2067""")
    }
    Get("/api/v1/analytics/margins/series?category=Seafood") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] should include(""""category":"Seafood"""")
    }
    Get("/api/v1/analytics/margins/series") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] should include(""""margin_date":"2024-03-01"""")
    }
  }

  "GET /margins/export?format=csv" should "emit the grid as CSV with escaped fields" in {
    Get("/api/v1/analytics/margins/export?format=csv") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`text/plain(UTF-8)`
      val lines = responseAs[String].split("\n").toList
      lines.head shouldBe
        "sku,name,category,supplier,list_price_usd,commodity_cost_usd,freight_cost_usd," +
        "overhead_cost_usd,cogs_usd,margin_pct"
      lines should have size 3
      // The salmon row's name contains a comma and must be quoted.
      lines(1) shouldBe
        """SLM-001,"Salmon Fillet, skin-on",Seafood,NordicCatch AS,30.00,10.0000,0.1200,1.5180,11.6380,61.2067"""
      lines(2) shouldBe "SGR-002,Cane Sugar 1kg,Grocery,Acme,4.00,1.0000,0.1000,0.1100,1.2100,69.7500"
    }
  }

  "GET /margins/export" should "default to the same JSON document as the grid" in {
    Get("/api/v1/analytics/margins/export") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      contentType shouldBe ContentTypes.`application/json`
      responseAs[String] should include(""""gross_margin_pct":65.48""")
    }
  }

  it should "ignore an unsupported format and fall back to JSON" in {
    Get("/api/v1/analytics/margins/export?format=xlsx") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] should include(""""rows":[""")
    }
  }
