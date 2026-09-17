package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.testkit.ScalatestRouteTest
import com.dimafeng.testcontainers.PostgreSQLContainer
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.db.AnalyticsDb
import com.otterworks.analytics.model.*
import com.otterworks.analytics.model.MarketJsonProtocol.{*, given}
import com.otterworks.analytics.repository.MarketRepository
import com.otterworks.analytics.service.MarginService
import org.scalatest.BeforeAndAfterAll
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import org.testcontainers.utility.DockerImageName

/**
 * The margin export endpoint: its default JSON rendering and the CSV escaping
 * of catalog text that contains separators or quotes.
 *
 * Requires Docker (Testcontainers); cancelled rather than failed without it.
 */
class MarginRoutesEdgeCaseSpec
    extends AnyFlatSpec with Matchers with ScalatestRouteTest with ScalaFutures with BeforeAndAfterAll:

  given PatienceConfig = PatienceConfig(timeout = Span(60, Seconds), interval = Span(100, Millis))

  private var container: Option[PostgreSQLContainer] = None
  private var db: Option[AnalyticsDb] = None
  private var routes: Option[MarginRoutes] = None

  private val awkwardName = """Salmon Fillet, 1kg ("premium")"""

  override def beforeAll(): Unit =
    super.beforeAll()
    try
      val c = PostgreSQLContainer(dockerImageNameOverride = DockerImageName.parse("postgres:15-alpine"))
      c.start()
      val database = new AnalyticsDb(PostgresConfig(c.jdbcUrl, c.username, c.password, maxPoolSize = 4))
      database.migrate()
      val repo = new MarketRepository(database)
      val marginService = new MarginService(repo)

      List(
        MarketSeries("SALMON_NOK_KG", "Salmon", "NOK/kg", "NOK", "commodity"),
        MarketSeries("USD_NOK", "USD/NOK", "NOK", "USD", "fx"),
        MarketSeries("DREWRY_WCI_USD_FEU", "Drewry WCI", "USD/FEU", "USD", "freight")
      ).foreach(s => repo.upsertSeries(s).futureValue)
      repo.upsertProduct(Product(
        "SLM-001", awkwardName, "Seafood", "SALMON_NOK_KG",
        BigDecimal("1.0"), BigDecimal("1.2"), BigDecimal("15.00"), BigDecimal("30.00"), "NordicCatch AS"
      )).futureValue
      List(
        ("SALMON_NOK_KG", BigDecimal(100)), ("USD_NOK", BigDecimal(10)), ("DREWRY_WCI_USD_FEU", BigDecimal(2500))
      ).foreach { case (code, value) => repo.upsertManualPrice(code, "2025-01-01", value).futureValue }
      marginService.recompute().futureValue

      container = Some(c)
      db = Some(database)
      routes = Some(MarginRoutes(marginService, repo))
    catch
      case ex: Throwable =>
        info(s"Docker/Postgres unavailable, skipping margin export tests: ${ex.getMessage}")
        container = None

  override def afterAll(): Unit =
    db.foreach(_.close())
    container.foreach(_.stop())
    super.afterAll()

  private def marginRoutes(): MarginRoutes =
    assume(routes.isDefined, "Docker not available")
    routes.get

  "GET /api/v1/analytics/margins/export" should "default to the JSON dashboard payload" in {
    Get("/api/v1/analytics/margins/export") ~> marginRoutes().routes ~> check {
      status shouldBe StatusCodes.OK
      val payload = responseAs[MarginsResponse]
      payload.asOfDate shouldBe "2025-01-01"
      payload.rows.map(_.sku) shouldBe List("SLM-001")
      payload.rows.head.marginPct shouldBe BigDecimal("61.2067")
      payload.kpis.salmonIndex shouldBe BigDecimal("100.00")
    }
  }

  it should "quote CSV fields that contain separators or quotes" in {
    Get("/api/v1/analytics/margins/export?format=csv") ~> marginRoutes().routes ~> check {
      status shouldBe StatusCodes.OK
      val csv = responseAs[String]
      val lines = csv.linesIterator.toList
      lines.head shouldBe
        "sku,name,category,supplier,list_price_usd,commodity_cost_usd,freight_cost_usd,overhead_cost_usd,cogs_usd,margin_pct"
      lines(1) should startWith("""SLM-001,"Salmon Fillet, 1kg (""premium"")",Seafood,NordicCatch AS,""")
      lines(1) should endWith("61.2067")
    }
  }
