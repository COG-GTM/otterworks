package com.otterworks.analytics.repository

import com.dimafeng.testcontainers.PostgreSQLContainer
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.db.AnalyticsDb
import com.otterworks.analytics.model.*
import org.scalatest.{BeforeAndAfterAll, BeforeAndAfterEach}
import org.scalatest.concurrent.ScalaFutures
import slick.jdbc.PostgresProfile.api.*
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import org.testcontainers.utility.DockerImageName

import java.time.Instant
import java.time.temporal.ChronoUnit
import scala.concurrent.{Await, ExecutionContext}
import scala.concurrent.duration.*

/**
 * Reconciliation baseline for the analytics lakehouse migration.
 *
 * Proves the durable PostgreSQL store returns byte-for-byte identical analytics
 * to the previous in-memory store for a seeded event set — the same invariant a
 * continuous-validation check will assert between this "before" store and the
 * future S3 + Iceberg "after".
 *
 * Requires Docker (Testcontainers). When Docker is unavailable the suite is
 * cancelled rather than failed, so it never breaks CI on Docker-less runners.
 */
class PostgresMetricsRepositorySpec extends AnyFlatSpec with Matchers with ScalaFutures with BeforeAndAfterAll with BeforeAndAfterEach:

  given PatienceConfig = PatienceConfig(timeout = Span(30, Seconds), interval = Span(100, Millis))
  given ExecutionContext = ExecutionContext.global

  private var container: Option[PostgreSQLContainer] = None
  private var db: Option[AnalyticsDb] = None

  override def beforeAll(): Unit =
    try
      val c = PostgreSQLContainer(dockerImageNameOverride = DockerImageName.parse("postgres:15-alpine"))
      c.start()
      val cfg = PostgresConfig(c.jdbcUrl, c.username, c.password, maxPoolSize = 4)
      val database = new AnalyticsDb(cfg)
      database.migrate()
      container = Some(c)
      db = Some(database)
    catch
      case ex: Throwable =>
        info(s"Docker/Postgres unavailable, skipping durable-store tests: ${ex.getMessage}")
        container = None

  override def afterAll(): Unit =
    db.foreach(_.close())
    container.foreach(_.stop())

  override def beforeEach(): Unit =
    // Isolate each test: the container is shared, so start from empty tables.
    db.foreach { database =>
      Await.result(
        database.database.run(sqlu"TRUNCATE analytics_events, analytics_daily_metrics RESTART IDENTITY"),
        10.seconds
      )
    }

  private def requireDb(): AnalyticsDb =
    assume(db.isDefined, "Docker not available")
    db.get

  // A deterministic event set anchored just before "now" so every event falls
  // inside all query windows (daily…90d). Timestamps are microsecond-precision
  // and spaced apart so ordering is stable and round-trips exactly through
  // Postgres (which we store as epoch-nanoseconds).
  private val base: Instant = Instant.now().truncatedTo(ChronoUnit.MICROS).minusSeconds(3600)
  private def at(i: Int): Instant = base.plusSeconds(i.toLong).plusNanos(i.toLong * 1000L)

  private val seed: List[AnalyticsEvent] = List(
    AnalyticsEvent("e01", EventType.DocumentCreated, "user-1", "doc-1", "document", Map("title" -> "Alpha"), at(1)),
    AnalyticsEvent("e02", EventType.DocumentViewed, "user-2", "doc-1", "document", Map("title" -> "Alpha"), at(2)),
    AnalyticsEvent("e03", EventType.DocumentEdited, "user-1", "doc-1", "document", Map("title" -> "Alpha"), at(3)),
    AnalyticsEvent("e04", EventType.DocumentShared, "user-1", "doc-1", "document", Map.empty, at(4)),
    AnalyticsEvent("e05", EventType.DocumentCreated, "user-2", "doc-2", "document", Map("title" -> "Beta"), at(5)),
    AnalyticsEvent("e06", EventType.FileUploaded, "user-1", "file-1", "file", Map("title" -> "F1"), at(6)),
    AnalyticsEvent("e07", EventType.FileDownloaded, "user-3", "file-1", "file", Map.empty, at(7)),
    AnalyticsEvent("e08", EventType.CollabSessionStarted, "user-2", "sess-1", "session", Map.empty, at(8)),
    AnalyticsEvent("e09", EventType.StorageAllocated, "user-1", "file-1", "file", Map("bytes" -> "2048"), at(9)),
    AnalyticsEvent("e10", EventType.StorageAllocated, "user-2", "file-2", "file", Map("bytes" -> "1024"), at(10)),
    AnalyticsEvent("e11", EventType.StorageReleased, "user-1", "file-1", "file", Map("bytes" -> "512"), at(11)),
    AnalyticsEvent("e12", EventType.DocumentViewed, "user-3", "doc-2", "document", Map("title" -> "Beta"), at(12))
  )

  private def seedInto(repo: MetricsRepository): Unit =
    // Insert sequentially so the durable store's serial ids preserve seed order.
    seed.foreach(e => Await.result(repo.storeEvent(e), 10.seconds))

  private def newInMemory(): InMemoryMetricsRepository =
    val r = new InMemoryMetricsRepository(PostgresConfig("", "", "", 1))
    seedInto(r)
    r

  "PostgresMetricsRepository" should "reconcile all analytics with the in-memory store" in {
    val database = requireDb()
    val pg = new PostgresMetricsRepository(database)
    seedInto(pg)
    val mem = newInMemory()

    for period <- List("7d", "30d", "90d", "daily", "weekly", "monthly") do
      pg.getDashboardSummary(period).futureValue shouldBe mem.getDashboardSummary(period).futureValue
      pg.getActiveUsers(period).futureValue shouldBe mem.getActiveUsers(period).futureValue
      pg.getExportData(period).futureValue shouldBe mem.getExportData(period).futureValue

    for ct <- List("documents", "files", "all") do
      pg.getTopContent(ct, "30d", 10).futureValue shouldBe mem.getTopContent(ct, "30d", 10).futureValue

    for user <- List("user-1", "user-2", "user-3", "user-unknown") do
      pg.getUserActivity(user).futureValue shouldBe mem.getUserActivity(user).futureValue

    for doc <- List("doc-1", "doc-2", "file-1") do
      pg.getDocumentStats(doc).futureValue shouldBe mem.getDocumentStats(doc).futureValue

    pg.getStorageUsage(None).futureValue shouldBe mem.getStorageUsage(None).futureValue
    pg.getStorageUsage(Some("user-1")).futureValue shouldBe mem.getStorageUsage(Some("user-1")).futureValue
    pg.getEventCount.futureValue shouldBe mem.getEventCount.futureValue
    pg.getEventCount.futureValue shouldBe seed.size.toLong
  }

  it should "match the reference dashboard values exactly" in {
    val database = requireDb()
    val pg = new PostgresMetricsRepository(database)
    seedInto(pg)

    val summary = pg.getDashboardSummary("30d").futureValue
    summary.totalEvents shouldBe 12
    summary.dailyActiveUsers shouldBe 3
    summary.documentsCreated shouldBe 2
    summary.filesUploaded shouldBe 1
    summary.collabSessions shouldBe 1
    summary.storageUsedBytes shouldBe 2560 // 2048 + 1024 - 512
  }

  it should "persist a daily aggregate rollup consistent with the event log" in {
    val database = requireDb()
    val pg = new PostgresMetricsRepository(database)
    seedInto(pg)

    val rollup = pg.getDailyMetrics.futureValue
    rollup.map(_.eventCount).sum shouldBe seed.size.toLong

    val expectedByType = seed.groupBy(_.eventType).view.mapValues(_.size.toLong).toMap
    val rollupByType = rollup.groupBy(_.eventType).view.mapValues(_.map(_.eventCount).sum).toMap
    rollupByType shouldBe expectedByType
  }

  it should "retain events durably across repository instances" in {
    val database = requireDb()
    val pg1 = new PostgresMetricsRepository(database)
    seedInto(pg1)
    val before = pg1.getEventCount.futureValue

    // A fresh repository over the same database sees the persisted events.
    val pg2 = new PostgresMetricsRepository(database)
    pg2.getEventCount.futureValue shouldBe before
  }

  it should "bound result sizes server-side and still reconcile with the in-memory store" in {
    val database = requireDb()
    val pg = new PostgresMetricsRepository(database)
    val n = MetricsAggregator.Limits.MaxExportRows + 50
    val newest = base.plusSeconds(1800)
    val events = (1 to n).map { i =>
      AnalyticsEvent(f"b$i%06d", EventType.DocumentViewed, s"user-${i % 1200}", s"doc-${i % 150}", "document",
        Map.empty, newest.minusNanos(i.toLong * 1000L))
    }
    val newestNanos = newest.getEpochSecond * 1000000000L + newest.getNano
    // Bulk insert in the same order as `events` so serial ids follow insertion order.
    Await.result(
      database.database.run(sqlu"""
        INSERT INTO analytics_events (event_id, event_type, user_id, resource_id, resource_type, metadata, occurred_at)
        SELECT 'b' || lpad(i::text, 6, '0'), ${EventType.DocumentViewed}, 'user-' || (i % 1200),
               'doc-' || (i % 150), 'document', '{}', ${newestNanos} - i * 1000
        FROM generate_series(1, ${n}) AS i ORDER BY i"""),
      30.seconds
    )
    val mem = new InMemoryMetricsRepository(PostgresConfig("", "", "", 1))
    events.foreach(e => Await.result(mem.storeEvent(e), 10.seconds))

    val export = pg.getExportData("7d").futureValue
    export should have size MetricsAggregator.Limits.MaxExportRows
    export.head("event_id") shouldBe "b000001"
    export shouldBe mem.getExportData("7d").futureValue

    val active = pg.getActiveUsers("7d").futureValue
    active.count shouldBe 1200
    active.users should have size MetricsAggregator.Limits.MaxActiveUsers
    active shouldBe mem.getActiveUsers("7d").futureValue

    val top = pg.getTopContent("documents", "7d", 10000).futureValue
    top.items should have size MetricsAggregator.Limits.MaxTopContent
    top shouldBe mem.getTopContent("documents", "7d", 10000).futureValue

    pg.getUserActivity("user-7").futureValue shouldBe mem.getUserActivity("user-7").futureValue
    pg.getDashboardSummary("7d").futureValue shouldBe mem.getDashboardSummary("7d").futureValue
  }

  it should "parse storage bytes exactly like the in-memory aggregation" in {
    val database = requireDb()
    val pg = new PostgresMetricsRepository(database)
    val odd = List(
      AnalyticsEvent("s1", EventType.StorageAllocated, "user-1", "f1", "file", Map("bytes" -> "100"), at(1)),
      AnalyticsEvent("s2", EventType.StorageAllocated, "user-1", "f2", "file", Map("bytes" -> Long.MaxValue.toString), at(2)),
      AnalyticsEvent("s3", EventType.StorageAllocated, "user-1", "f3", "document", Map("bytes" -> "9223372036854775808"), at(3)),
      AnalyticsEvent("s4", EventType.StorageReleased, "user-1", "f1", "file", Map("bytes" -> "-5"), at(4)),
      AnalyticsEvent("s5", EventType.StorageAllocated, "user-2", "f4", "file", Map("bytes" -> "abc"), at(5)),
      AnalyticsEvent("s6", EventType.StorageAllocated, "user-2", "f5", "image", Map.empty, at(6)),
      AnalyticsEvent("s7", EventType.StorageAllocated, "user-2", "f6", "file", Map("bytes" -> "+42"), at(7)),
      AnalyticsEvent("s8", EventType.StorageReleased, "user-2", "f6", "file", Map("bytes" -> "7"), at(8))
    )
    odd.foreach(e => Await.result(pg.storeEvent(e), 10.seconds))
    val mem = new InMemoryMetricsRepository(PostgresConfig("", "", "", 1))
    odd.foreach(e => Await.result(mem.storeEvent(e), 10.seconds))

    for user <- List(None, Some("user-1"), Some("user-2"), Some("nobody")) do
      pg.getStorageUsage(user).futureValue shouldBe mem.getStorageUsage(user).futureValue
    pg.getDashboardSummary("30d").futureValue shouldBe mem.getDashboardSummary("30d").futureValue
  }
