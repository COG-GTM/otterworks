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
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.testcontainers.utility.DockerImageName
import slick.dbio.DBIO
import spray.json.*

import java.time.LocalDate
import scala.concurrent.duration.*
import scala.concurrent.{Await, Future}

/**
 * Margin query paths the end-to-end seed spec does not reach, against a real
 * PostgreSQL (Testcontainers; cancelled when Docker is unavailable):
 *   - the dashboard and a recompute on an empty (migrated but unseeded) schema
 *   - `marginSeries` filtered by sku, by category and unfiltered
 *   - observation validation for future-dated pulls
 *   - the /margins/export JSON and CSV renderings, including CSV quoting
 *
 * The fixture is a small hand-built dataset rather than the 40-SKU baseline so
 * every expected number in here is checkable by hand.
 */
class MarginQueriesIntegrationSpec
    extends AnyFlatSpec
    with Matchers
    with ScalatestRouteTest
    with BeforeAndAfterAll:

  private var container: Option[PostgreSQLContainer] = None
  private var db: Option[AnalyticsDb] = None
  private var repo: Option[MarketRepository] = None
  private var marginService: Option[MarginService] = None

  override def beforeAll(): Unit =
    super.beforeAll()
    try
      val c = PostgreSQLContainer(dockerImageNameOverride = DockerImageName.parse("postgres:15-alpine"))
      c.start()
      val database = new AnalyticsDb(PostgresConfig(c.jdbcUrl, c.username, c.password, maxPoolSize = 4))
      database.migrate()
      container = Some(c)
      db = Some(database)
      repo = Some(new MarketRepository(database))
      marginService = repo.map(new MarginService(_))
    catch
      case ex: Throwable =>
        info(s"Docker/Postgres unavailable, skipping margin query tests: ${ex.getMessage}")
        container = None

  override def afterAll(): Unit =
    db.foreach(_.close())
    container.foreach(_.stop())
    super.afterAll()

  private def requireStack(): (MarketRepository, MarginService) =
    assume(repo.isDefined, "Docker not available")
    (repo.get, marginService.get)

  private def await[A](f: Future[A]): A = Await.result(f, 30.seconds)

  private val salmon = MarketSeries("SALMON_NOK_KG", "Salmon spot", "NOK/kg", "NOK", "commodity")
  private val fx = MarketSeries("USD_NOK", "USD/NOK", "NOK", "NOK", "fx")
  private val freight = MarketSeries("DREWRY_WCI_USD_FEU", "Drewry WCI", "USD/FEU", "USD", "freight")

  private val fillet = Product(
    "SLM-100", "Salmon Fillet", "Seafood", salmon.seriesCode,
    BigDecimal(1), BigDecimal(1), BigDecimal(10), BigDecimal(30), "NordicCatch AS")
  private val portions = Product(
    "SLM-101", "Salmon Portions", "Seafood", salmon.seriesCode,
    BigDecimal(1), BigDecimal(1), BigDecimal(10), BigDecimal(20), "NordicCatch AS")
  private val awkward = Product(
    "CSV-001", """Bundle, "Family" size""", "Retail", salmon.seriesCode,
    BigDecimal(1), BigDecimal(1), BigDecimal(10), BigDecimal(50), """Grocer, Inc.""")

  private def margin(sku: String, date: String, marginPct: String) =
    MarginDaily(sku, date, BigDecimal(1), BigDecimal(1), BigDecimal(1), BigDecimal(3), BigDecimal(marginPct))

  private def routes =
    val (r, svc) = requireStack()
    akka.http.scaladsl.server.Directives.concat(
      MarginRoutes(svc, r).routes,
      MarketIngestRoutes(svc, r).routes,
    )

  // --- empty schema (runs before the fixture is inserted) ---

  "marginsDashboard" should "return zeroed KPIs on a migrated but unseeded schema" in {
    val (_, svc) = requireStack()

    val response = await(svc.marginsDashboard())

    response.rows shouldBe empty
    response.asOfDate shouldBe ""
    response.kpis.grossMarginPct shouldBe BigDecimal("0.00")
    response.kpis.avgCogsUsd shouldBe BigDecimal("0.00")
    response.kpis.salmonIndex shouldBe BigDecimal("0.00")
    response.kpis.freightIndex shouldBe BigDecimal("0.00")
  }

  "recompute" should "be a no-op when there are no products or prices" in {
    val (_, svc) = requireStack()

    await(svc.recompute()) shouldBe 0
  }

  "pricesForSeries" should "short-circuit on an empty series list" in {
    val (r, _) = requireStack()

    await(r.pricesForSeries(Seq.empty)) shouldBe empty
  }

  // --- fixture ---

  "the fixture" should "insert series, products and margins" in {
    val (r, _) = requireStack()

    await(Future.sequence(List(salmon, fx, freight).map(r.upsertSeries))).sum shouldBe 3
    await(Future.sequence(List(fillet, portions, awkward).map(r.upsertProduct))).sum shouldBe 3
    await(r.upsertManualPrice(salmon.seriesCode, "2026-01-01", BigDecimal("100.00"))) shouldBe 1
    await(r.upsertManualPrice(freight.seriesCode, "2026-01-01", BigDecimal("2500.00"))) shouldBe 1

    val margins = List(
      margin(fillet.sku, "2026-01-01", "60.0000"),
      margin(fillet.sku, "2026-01-02", "50.0000"),
      margin(fillet.sku, "2026-01-03", "40.0000"),
      margin(portions.sku, "2026-01-02", "30.0000"),
      margin(awkward.sku, "2026-01-03", "20.0000"),
    )
    await(r.run(DBIO.sequence(margins.map(r.upsertMargin)))).sum shouldBe margins.size

    await(r.latestMarginDate()) shouldBe Some("2026-01-03")
  }

  // --- margin series ---

  "marginSeries" should "return one point per date for a single sku" in {
    val (r, _) = requireStack()

    val points = await(r.marginSeries(Some(fillet.sku), None, None, None))

    points.map(_.marginDate) shouldBe Seq("2026-01-01", "2026-01-02", "2026-01-03")
    points.map(_.marginPct) shouldBe Seq(BigDecimal("60.0000"), BigDecimal("50.0000"), BigDecimal("40.0000"))
  }

  it should "honour the from/to window" in {
    val (r, _) = requireStack()

    val points = await(r.marginSeries(Some(fillet.sku), None, Some("2026-01-02"), Some("2026-01-02")))

    points.map(_.marginDate) shouldBe Seq("2026-01-02")
  }

  it should "average across the products of a category" in {
    val (r, _) = requireStack()

    val points = await(r.marginSeries(None, Some("Seafood"), None, None))

    // 2026-01-02 averages the fillet (50) and the portions (30); the Retail SKU is excluded.
    points.map(p => (p.marginDate, p.marginPct)) shouldBe Seq(
      ("2026-01-01", BigDecimal("60.0000")),
      ("2026-01-02", BigDecimal("40.0000")),
      ("2026-01-03", BigDecimal("40.0000")),
    )
  }

  it should "ignore the category when a sku is given" in {
    val (r, _) = requireStack()

    await(r.marginSeries(Some(portions.sku), Some("Retail"), None, None)).map(_.marginDate) shouldBe Seq("2026-01-02")
  }

  it should "average across every product when neither sku nor category is given" in {
    val (r, _) = requireStack()

    val points = await(r.marginSeries(None, None, None, None))

    // 2026-01-03 averages the fillet (40) and the awkwardly named Retail SKU (20).
    points.map(p => (p.marginDate, p.marginPct)) shouldBe Seq(
      ("2026-01-01", BigDecimal("60.0000")),
      ("2026-01-02", BigDecimal("40.0000")),
      ("2026-01-03", BigDecimal("30.0000")),
    )
  }

  // --- observation validation ---

  "ingest" should "reject an observation dated in the future" in {
    val (_, svc) = requireStack()
    val tomorrow = LocalDate.now().plusDays(1).toString
    val request = ObservationsRequest(
      List(Observation(salmon.seriesCode, tomorrow, BigDecimal("120.00"))),
      Some("unit test")
    )

    val result = await(svc.ingest(request))

    result.isLeft shouldBe true
    val rejected = result.swap.getOrElse(Nil)
    rejected.map(_.reason) shouldBe List("price_date is in the future")
    rejected.map(_.priceDate) shouldBe List(tomorrow)
  }

  // --- export rendering ---

  "GET /api/v1/analytics/margins/export" should "default to the JSON dashboard payload" in {
    requireStack()

    Get("/api/v1/analytics/margins/export") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      val body = responseAs[MarginsResponse]
      body.asOfDate shouldBe "2026-01-03"
      body.rows.map(_.sku).sorted shouldBe List(awkward.sku, fillet.sku, portions.sku)
    }
  }

  it should "render CSV with quoted fields for values containing separators" in {
    requireStack()

    Get("/api/v1/analytics/margins/export?format=csv") ~> routes ~> check {
      status shouldBe StatusCodes.OK
      val lines = responseAs[String].linesIterator.toList
      lines.head shouldBe
        "sku,name,category,supplier,list_price_usd,commodity_cost_usd,freight_cost_usd,overhead_cost_usd,cogs_usd,margin_pct"
      lines should have size 4

      val awkwardRow = lines.find(_.startsWith(awkward.sku)).getOrElse(fail("CSV-001 row missing"))
      awkwardRow should include("""Bundle, ""Family"" size""")
      awkwardRow should include(""""Grocer, Inc."""")

      val plainRow = lines.find(_.startsWith(fillet.sku)).getOrElse(fail("SLM-100 row missing"))
      plainRow should not include "\""
    }
  }
