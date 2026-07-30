package com.otterworks.analytics.repository

import com.dimafeng.testcontainers.PostgreSQLContainer
import com.otterworks.analytics.batch.MarketSeeder
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.db.AnalyticsDb
import com.otterworks.analytics.model.*
import com.otterworks.analytics.service.MarginService
import org.scalatest.BeforeAndAfterAll
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import org.testcontainers.utility.DockerImageName
import slick.jdbc.PostgresProfile.api.*

import java.time.{Instant, LocalDate}
import scala.concurrent.ExecutionContext

/**
 * Market/margin behaviour on the boundaries the happy-path integration suite
 * never reaches: an empty store, a product whose commodity series has no
 * prices, the category/all variants of the margin series query, and a JDBC URL
 * that carries no query string.
 *
 * Requires Docker (Testcontainers); cancelled rather than failed without it,
 * like the other durable-store suites.
 */
class MarketDataEdgeCaseSpec extends AnyFlatSpec with Matchers with ScalaFutures with BeforeAndAfterAll:

  given PatienceConfig = PatienceConfig(timeout = Span(60, Seconds), interval = Span(100, Millis))
  given ExecutionContext = ExecutionContext.global

  private var container: Option[PostgreSQLContainer] = None
  private var db: Option[AnalyticsDb] = None
  private var repo: Option[MarketRepository] = None
  private var service: Option[MarginService] = None

  override def beforeAll(): Unit =
    try
      val c = PostgreSQLContainer(dockerImageNameOverride = DockerImageName.parse("postgres:15-alpine"))
      c.start()
      val database = new AnalyticsDb(PostgresConfig(c.jdbcUrl, c.username, c.password, maxPoolSize = 4))
      database.migrate()
      container = Some(c)
      db = Some(database)
      repo = Some(new MarketRepository(database))
      service = Some(new MarginService(repo.get))
    catch
      case ex: Throwable =>
        info(s"Docker/Postgres unavailable, skipping market edge-case tests: ${ex.getMessage}")
        container = None

  override def afterAll(): Unit =
    db.foreach(_.close())
    container.foreach(_.stop())

  private def requireStack(): (MarketRepository, MarginService) =
    assume(repo.isDefined, "Docker not available")
    (repo.get, service.get)

  // ── empty store ───────────────────────────────────────────────

  "An empty market store" should "recompute nothing and report zeroed KPIs" in {
    val (r, svc) = requireStack()

    svc.recompute().futureValue shouldBe 0
    r.latestMarginDate().futureValue shouldBe None
    r.pricesForSeries(Seq.empty).futureValue shouldBe empty

    val dashboard = svc.marginsDashboard().futureValue
    dashboard.rows shouldBe empty
    dashboard.asOfDate shouldBe ""
    dashboard.source shouldBe "synthetic"
    dashboard.lastSyncAt shouldBe None
    dashboard.kpis shouldBe MarginKpis(BigDecimal("0.00"), BigDecimal("0.00"), BigDecimal("0.00"), BigDecimal("0.00"))
  }

  it should "answer every margin-series variant with an empty list" in {
    val (r, _) = requireStack()

    r.marginSeries(Some("SLM-001"), None, None, None).futureValue shouldBe empty
    r.marginSeries(None, Some("Seafood"), None, None).futureValue shouldBe empty
    r.marginSeries(None, None, None, None).futureValue shouldBe empty
  }

  // ── hand-built catalog ────────────────────────────────────────

  private val salmon = MarketSeries("SALMON_NOK_KG", "Salmon", "NOK/kg", "NOK", "commodity")
  private val fx = MarketSeries("USD_NOK", "USD/NOK", "NOK", "USD", "fx")
  private val freight = MarketSeries("DREWRY_WCI_USD_FEU", "Drewry WCI", "USD/FEU", "USD", "freight")
  private val orphan = MarketSeries("ORPHAN_USD_KG", "Unpriced commodity", "USD/kg", "USD", "commodity")

  private val salmonProduct = Product(
    "SLM-001", "Atlantic Salmon Fillet", "Seafood", "SALMON_NOK_KG",
    BigDecimal("1.0"), BigDecimal("1.2"), BigDecimal("15.00"), BigDecimal("30.00"), "NordicCatch AS")
  private val orphanProduct = salmonProduct.copy(
    sku = "ORP-001", name = "Unpriced Product", commoditySeriesCode = "ORPHAN_USD_KG")

  private val day1 = "2025-01-01"
  private val day2 = "2025-01-02"

  "A catalog with an unpriced commodity series" should "produce margins only for priced products" in {
    val (r, svc) = requireStack()

    List(salmon, fx, freight, orphan).foreach(s => r.upsertSeries(s).futureValue)
    List(salmonProduct, orphanProduct).foreach(p => r.upsertProduct(p).futureValue)
    for
      (code, value) <- List(
        ("SALMON_NOK_KG", BigDecimal(100)), ("USD_NOK", BigDecimal(10)), ("DREWRY_WCI_USD_FEU", BigDecimal(2500)))
      date <- List(day1, day2)
    do r.upsertManualPrice(code, date, value).futureValue

    // Both products are targeted, but only the priced one yields margin rows.
    svc.recompute().futureValue shouldBe 2

    val rows = r.marginRowsLatest().futureValue
    rows.map(_.sku) shouldBe Seq("SLM-001")
    rows.head.marginPct shouldBe BigDecimal("61.2067")
    r.latestMarginDate().futureValue shouldBe Some(day2)
  }

  it should "serve the sku, category and all-products margin series" in {
    val (r, _) = requireStack()

    r.marginSeries(Some("SLM-001"), None, None, None).futureValue.map(_.marginDate) shouldBe Seq(day1, day2)
    r.marginSeries(None, Some("Seafood"), None, None).futureValue.map(_.marginDate) shouldBe Seq(day1, day2)
    r.marginSeries(None, None, None, None).futureValue.map(_.marginDate) shouldBe Seq(day1, day2)
    r.marginSeries(None, None, Some(day2), None).futureValue.map(_.marginDate) shouldBe Seq(day2)
    r.marginSeries(None, Some("Unknown category"), None, None).futureValue shouldBe empty
  }

  it should "list prices unbounded and by series set" in {
    val (r, _) = requireStack()

    r.listPrices("SALMON_NOK_KG", None, None).futureValue.map(_.priceDate) shouldBe Seq(day1, day2)
    r.listPrices("SALMON_NOK_KG", Some(day2), Some(day2)).futureValue.map(_.value) shouldBe Seq(BigDecimal(100))
    r.pricesForSeries(Seq("USD_NOK", "SALMON_NOK_KG")).futureValue.map(_.seriesCode).distinct shouldBe
      Seq("SALMON_NOK_KG", "USD_NOK")
  }

  it should "update catalog rows in place on re-upsert" in {
    val (r, _) = requireStack()

    r.upsertSeries(salmon.copy(name = "Salmon (renamed)")).futureValue
    r.upsertProduct(salmonProduct.copy(supplier = "NordicCatch II")).futureValue

    r.listSeries().futureValue.find(_.seriesCode == "SALMON_NOK_KG").map(_.name) shouldBe Some("Salmon (renamed)")
    r.listProducts().futureValue.find(_.sku == "SLM-001").map(_.supplier) shouldBe Some("NordicCatch II")
  }

  "Observation ingest" should "reject a price dated in the future" in {
    val (_, svc) = requireStack()
    val tomorrow = LocalDate.now().plusDays(1).toString

    val result = svc.ingest(ObservationsRequest(List(Observation("SALMON_NOK_KG", tomorrow, BigDecimal(101))), None)).futureValue
    result.isLeft shouldBe true
    result.swap.getOrElse(Nil).map(_.reason) shouldBe List("price_date is in the future")
  }

  "MarketSeeder.run" should "default the walk horizon to today" in {
    val (r, svc) = requireStack()

    MarketSeeder.run(r, svc) should be > 0
    r.listSeries().futureValue.map(_.seriesCode) should contain("SUGAR_USD_KG")
    r.latestMarginDate().futureValue shouldBe Some(LocalDate.now().toString)
  }

  // ── durable event store ───────────────────────────────────────

  "PostgresMetricsRepository" should "read a legacy row whose metadata column is empty" in {
    assume(db.isDefined, "Docker not available")
    val database = db.get
    val store = new PostgresMetricsRepository(database)
    val occurredAtNanos = Instant.now().getEpochSecond * 1000000000L

    database.database.run(
      sqlu"""INSERT INTO analytics_events
               (event_id, event_type, user_id, resource_id, resource_type, metadata, occurred_at)
             VALUES ('legacy-1', 'document.viewed', 'user-1', 'doc-legacy', 'document', '', $occurredAtNanos)"""
    ).futureValue shouldBe 1

    val item = store.getTopContent("documents", "7d", 10).futureValue.items.head
    item.resourceId shouldBe "doc-legacy"
    item.title shouldBe "doc-legacy" // no metadata to take a title from
  }

  // ── connection string handling ────────────────────────────────

  "AnalyticsDb" should "append the analytics schema to a URL without a query string" in {
    val c = container.getOrElse(cancel("Docker not available"))
    val plainUrl = c.jdbcUrl.takeWhile(_ != '?')
    plainUrl should not include "?"

    val database = new AnalyticsDb(PostgresConfig(plainUrl, c.username, c.password, maxPoolSize = 1))
    try database.database.run(sql"SELECT current_schema()".as[String].head).futureValue shouldBe "analytics"
    finally database.close()
  }
