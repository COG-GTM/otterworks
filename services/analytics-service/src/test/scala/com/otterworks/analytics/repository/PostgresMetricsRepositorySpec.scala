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

  it should "reconcile with the in-memory store for out-of-window events, ties and odd byte counts" in {
    val database = requireDb()
    val pg = new PostgresMetricsRepository(database)
    val old = Instant.now().truncatedTo(ChronoUnit.MICROS).minus(200, ChronoUnit.DAYS)
    val extra = List(
      AnalyticsEvent("x01", EventType.DocumentViewed, "user-9", "doc-9", "document", Map("title" -> "Old"), old),
      AnalyticsEvent("x02", EventType.StorageAllocated, "user-9", "file-9", "file", Map("bytes" -> "4096"), old),
      AnalyticsEvent("x03", EventType.StorageAllocated, "user-1", "file-3", "file", Map("bytes" -> "abc"), at(13)),
      AnalyticsEvent("x04", EventType.StorageAllocated, "user-1", "doc-1", "document", Map("bytes" -> "+7"), at(14)),
      AnalyticsEvent("x05", EventType.StorageReleased, "user-2", "file-2", "file", Map("bytes" -> "99999999999999999999"), at(15)),
      AnalyticsEvent("x06", EventType.StorageAllocated, "user-3", "file-4", "file", Map.empty, at(16)),
      AnalyticsEvent("x07", EventType.FileDownloaded, "user-2", "file-2", "file", Map.empty, at(17)),
      AnalyticsEvent("x08", EventType.FileDownloaded, "user-3", "file-2", "file", Map.empty, at(17)),
      AnalyticsEvent("x09", EventType.StorageAllocated, "user-1", "file-5", "file", Map("bytes" -> "\u0000"), at(18)),
      AnalyticsEvent("x10", EventType.StorageAllocated, "user-1", "file-6", "file",
        Map("note" -> "a\u0000b", "bytes" -> "11"), at(18)),
      AnalyticsEvent("x11", EventType.StorageAllocated, "user-2", "file-7", "file", Map("bytes" -> ("9" * 200000)), at(19)),
      AnalyticsEvent("x12", EventType.StorageAllocated, "user-2", "file-8", "file", Map("bytes" -> "\u0661\u0662\u0663"), at(19)),
      AnalyticsEvent("x13", EventType.StorageAllocated, "user-3", "file-9", "file", Map("bytes" -> "00000000000000000042"), at(20)),
      AnalyticsEvent("x14", EventType.StorageAllocated, "user-3", "file-10", "file", Map("bytes" -> ("-" + "0" * 200000 + "5")), at(20))
    )
    val events = seed ++ extra
    events.foreach(e => Await.result(pg.storeEvent(e), 10.seconds))
    val mem = new InMemoryMetricsRepository(PostgresConfig("", "", "", 1))
    events.foreach(e => Await.result(mem.storeEvent(e), 10.seconds))

    for period <- List("7d", "30d", "90d", "daily", "weekly", "monthly", "bogus") do
      pg.getDashboardSummary(period).futureValue shouldBe mem.getDashboardSummary(period).futureValue
      pg.getActiveUsers(period).futureValue shouldBe mem.getActiveUsers(period).futureValue
      pg.getExportData(period).futureValue shouldBe mem.getExportData(period).futureValue
      for ct <- List("documents", "files", "all"); limit <- List(-1, 0, 1, 2, 10, 1000) do
        pg.getTopContent(ct, period, limit).futureValue shouldBe mem.getTopContent(ct, period, limit).futureValue

    for user <- List("user-1", "user-2", "user-3", "user-9") do
      pg.getUserActivity(user).futureValue shouldBe mem.getUserActivity(user).futureValue
      pg.getStorageUsage(Some(user)).futureValue shouldBe mem.getStorageUsage(Some(user)).futureValue
    pg.getStorageUsage(None).futureValue shouldBe mem.getStorageUsage(None).futureValue
    for doc <- List("doc-1", "doc-9", "file-2") do
      pg.getDocumentStats(doc).futureValue shouldBe mem.getDocumentStats(doc).futureValue

    pg.getDashboardSummary("90d").futureValue.totalEvents shouldBe (events.size - 2).toLong
  }

  it should "bound the size of export, top-content and active-users responses" in {
    val database = requireDb()
    val pg = new PostgresMetricsRepository(database)
    val rows = MetricsAggregator.MaxExportRows + 50
    val recent = (Instant.now().minusSeconds(60).getEpochSecond) * 1000000000L
    Await.result(
      database.database.run(
        sqlu"""INSERT INTO analytics_events
                 (event_id, event_type, user_id, resource_id, resource_type, metadata, occurred_at)
               SELECT 'bulk-' || g, ${EventType.DocumentViewed}, 'user-' || g, 'doc-' || g, 'document', '{}',
                      ${recent} + g
               FROM generate_series(1, ${rows}) AS g"""
      ),
      60.seconds
    )

    val exported = pg.getExportData("7d").futureValue
    exported.size shouldBe MetricsAggregator.MaxExportRows
    exported.head("event_id") shouldBe s"bulk-$rows"

    pg.getTopContent("documents", "7d", Int.MaxValue).futureValue.items.size shouldBe MetricsAggregator.MaxTopContentLimit

    val active = pg.getActiveUsers("7d").futureValue
    active.count shouldBe rows.toLong
    active.users.size shouldBe MetricsAggregator.MaxActiveUsers
  }
