package com.otterworks.analytics.qa

import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.MetricsAggregator
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.time.Instant
import java.time.temporal.ChronoUnit

/** QA audit (docs/qa/analytics-report.md): pure aggregation semantics. */
class QaMetricsAggregatorSpec extends AnyFlatSpec with Matchers:

  private val now = Instant.now()

  private def ev(
      eventType: String,
      userId: String = "u1",
      resourceId: String = "r1",
      resourceType: String = "document",
      metadata: Map[String, String] = Map.empty,
      ageHours: Long = 1
  ): AnalyticsEvent =
    AnalyticsEvent(
      java.util.UUID.randomUUID().toString,
      eventType,
      userId,
      resourceId,
      resourceType,
      metadata,
      now.minus(ageHours, ChronoUnit.HOURS)
    )

  "periodToCutoff" should "map every documented period to the right window" in {
    val expected = Map(
      "daily" -> 1L, "7d" -> 7L, "weekly" -> 7L, "30d" -> 30L, "monthly" -> 30L, "90d" -> 90L
    )
    expected.foreach { case (period, days) =>
      val cutoff = MetricsAggregator.periodToCutoff(period)
      val delta = ChronoUnit.HOURS.between(cutoff, Instant.now())
      withClue(period) { delta shouldBe (days * 24) +- 1 }
    }
  }

  it should "fall back to a 7 day window for unknown periods" in {
    val delta = ChronoUnit.HOURS.between(MetricsAggregator.periodToCutoff("bogus"), Instant.now())
    delta shouldBe (7L * 24) +- 1
  }

  "dashboardSummary" should "count only events inside the period" in {
    val events = Seq(
      ev(EventType.DocumentCreated, userId = "a"),
      ev(EventType.DocumentCreated, userId = "b", ageHours = 24 * 10),
      ev(EventType.FileUploaded, userId = "a", resourceType = "file"),
      ev(EventType.CollabSessionStarted, userId = "c")
    )
    val s = MetricsAggregator.dashboardSummary(events, "7d")
    s.period shouldBe "7d"
    s.documentsCreated shouldBe 1
    s.filesUploaded shouldBe 1
    s.collabSessions shouldBe 1
    s.dailyActiveUsers shouldBe 2
    s.totalEvents shouldBe 3

    val wide = MetricsAggregator.dashboardSummary(events, "30d")
    wide.documentsCreated shouldBe 2
    wide.dailyActiveUsers shouldBe 3
  }

  it should "net storage allocations against releases and never go negative" in {
    val events = Seq(
      ev(EventType.StorageAllocated, metadata = Map("bytes" -> "1000")),
      ev(EventType.StorageReleased, metadata = Map("bytes" -> "400"))
    )
    MetricsAggregator.dashboardSummary(events, "7d").storageUsedBytes shouldBe 600
    val over = events :+ ev(EventType.StorageReleased, metadata = Map("bytes" -> "5000"))
    MetricsAggregator.dashboardSummary(over, "7d").storageUsedBytes shouldBe 0
  }

  it should "ignore malformed byte counts instead of failing" in {
    val events = Seq(
      ev(EventType.StorageAllocated, metadata = Map("bytes" -> "not-a-number")),
      ev(EventType.StorageAllocated, metadata = Map("bytes" -> "10"))
    )
    MetricsAggregator.dashboardSummary(events, "7d").storageUsedBytes shouldBe 10
  }

  it should "return zeros for an empty event set" in {
    val s = MetricsAggregator.dashboardSummary(Seq.empty, "30d")
    (s.totalEvents, s.dailyActiveUsers, s.storageUsedBytes) shouldBe (0L, 0L, 0L)
  }

  "userActivity" should "only include the requested user's events, newest first, capped at 20" in {
    val mine = (1 to 25).map(i => ev(EventType.DocumentViewed, userId = "me", ageHours = i))
    val other = Seq(ev(EventType.DocumentCreated, userId = "other"))
    val a = MetricsAggregator.userActivity(mine ++ other, "me")
    a.totalEvents shouldBe 25
    a.documentsViewed shouldBe 25
    a.documentsCreated shouldBe 0
    a.recentEvents should have size 20
    a.lastActiveAt shouldBe Some(mine.head.timestamp.toString)
    a.recentEvents.map(_.timestamp) shouldBe a.recentEvents.map(_.timestamp).sorted.reverse
  }

  it should "return an empty activity for an unknown user" in {
    val a = MetricsAggregator.userActivity(Seq(ev(EventType.DocumentCreated)), "nobody")
    a.totalEvents shouldBe 0
    a.lastActiveAt shouldBe None
    a.recentEvents shouldBe empty
  }

  "documentStats" should "count views/edits/shares and unique viewers per document" in {
    val events = Seq(
      ev(EventType.DocumentViewed, userId = "a", resourceId = "d1"),
      ev(EventType.DocumentViewed, userId = "a", resourceId = "d1"),
      ev(EventType.DocumentViewed, userId = "b", resourceId = "d1"),
      ev(EventType.DocumentEdited, userId = "a", resourceId = "d1"),
      ev(EventType.DocumentShared, userId = "a", resourceId = "d1"),
      ev(EventType.DocumentViewed, userId = "z", resourceId = "d2")
    )
    val s = MetricsAggregator.documentStats(events, "d1")
    (s.views, s.edits, s.shares, s.uniqueViewers) shouldBe (3L, 1L, 1L, 2L)
    s.lastViewedAt shouldBe defined
    s.lastEditedAt shouldBe defined
  }

  "topContent" should "filter by content type, rank by event count and honour the limit" in {
    val events =
      Seq.fill(3)(ev(EventType.DocumentViewed, resourceId = "d1", metadata = Map("title" -> "Doc One"))) ++
        Seq.fill(2)(ev(EventType.DocumentViewed, resourceId = "d2")) ++
        Seq.fill(5)(ev(EventType.FileDownloaded, resourceId = "f1", resourceType = "file"))
    val docs = MetricsAggregator.topContent(events, "documents", "7d", 10)
    docs.items.map(_.resourceId) shouldBe List("d1", "d2")
    docs.items.head.title shouldBe "Doc One"
    docs.items(1).title shouldBe "d2"
    MetricsAggregator.topContent(events, "files", "7d", 10).items.map(_.resourceId) shouldBe List("f1")
    MetricsAggregator.topContent(events, "all", "7d", 10).items.map(_.resourceId) shouldBe List("f1", "d1", "d2")
    MetricsAggregator.topContent(events, "all", "7d", 1).items should have size 1
  }

  "activeUsers" should "rank users by event count within the period" in {
    val events = Seq(
      ev(EventType.DocumentViewed, userId = "a"),
      ev(EventType.DocumentViewed, userId = "a"),
      ev(EventType.DocumentViewed, userId = "b"),
      ev(EventType.DocumentViewed, userId = "old", ageHours = 48)
    )
    val r = MetricsAggregator.activeUsers(events, "daily")
    r.count shouldBe 2
    r.users.map(_.userId) shouldBe List("a", "b")
  }

  "storageUsage" should "scope totals and breakdown to the requested user" in {
    val events = Seq(
      ev(EventType.StorageAllocated, userId = "a", resourceType = "file", metadata = Map("bytes" -> "100")),
      ev(EventType.StorageAllocated, userId = "a", resourceType = "document", metadata = Map("bytes" -> "50")),
      ev(EventType.FileUploaded, userId = "a", resourceType = "file"),
      ev(EventType.StorageAllocated, userId = "b", resourceType = "file", metadata = Map("bytes" -> "999"))
    )
    val a = MetricsAggregator.storageUsage(events, Some("a"))
    a.totalStorageBytes shouldBe 150
    a.filesCount shouldBe 1
    a.breakdownByType shouldBe Map("file" -> 100L, "document" -> 50L)
    MetricsAggregator.storageUsage(events, None).totalStorageBytes shouldBe 1149
  }

  "exportData" should "emit rows newest-first restricted to the period" in {
    val events = Seq(
      ev(EventType.DocumentCreated, resourceId = "older", ageHours = 5),
      ev(EventType.DocumentCreated, resourceId = "newer", ageHours = 1),
      ev(EventType.DocumentCreated, resourceId = "outside", ageHours = 24 * 40)
    )
    val rows = MetricsAggregator.exportData(events, "30d")
    rows.map(_("resource_id")) shouldBe List("newer", "older")
    rows.head.keySet shouldBe Set("event_id", "event_type", "user_id", "resource_id", "resource_type", "timestamp")
  }
