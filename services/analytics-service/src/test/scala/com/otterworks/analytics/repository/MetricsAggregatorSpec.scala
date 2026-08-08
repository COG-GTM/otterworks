package com.otterworks.analytics.repository

import com.otterworks.analytics.model.*
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.time.Instant

/** Window resolution and the aggregations that the two backends share. */
class MetricsAggregatorSpec extends AnyFlatSpec with Matchers:

  private val now = Instant.now()
  private def event(
      id: String,
      eventType: String,
      userId: String,
      resourceId: String,
      resourceType: String,
      metadata: Map[String, String] = Map.empty,
      at: Instant = Instant.now()
  ) = AnalyticsEvent(id, eventType, userId, resourceId, resourceType, metadata, at)

  "periodToCutoff" should "map every documented period to its window" in {
    MetricsAggregator.periodToCutoff("daily") should be > now.minusSeconds(24 * 3600 + 60)
    MetricsAggregator.periodToCutoff("7d").isBefore(MetricsAggregator.periodToCutoff("daily")) shouldBe true
    MetricsAggregator.periodToCutoff("weekly").isBefore(MetricsAggregator.periodToCutoff("daily")) shouldBe true
    MetricsAggregator.periodToCutoff("30d").isBefore(MetricsAggregator.periodToCutoff("7d")) shouldBe true
    MetricsAggregator.periodToCutoff("monthly").isBefore(MetricsAggregator.periodToCutoff("7d")) shouldBe true
    MetricsAggregator.periodToCutoff("90d").isBefore(MetricsAggregator.periodToCutoff("30d")) shouldBe true
  }

  it should "fall back to the 7-day window for an unknown period" in {
    val unknown = MetricsAggregator.periodToCutoff("last-fortnight")
    val sevenDays = MetricsAggregator.periodToCutoff("7d")
    java.time.Duration.between(unknown, sevenDays).abs().getSeconds should be < 5L
  }

  "dashboardSummary" should "clamp a net-negative storage balance to zero" in {
    val events = Seq(
      event("e1", EventType.StorageAllocated, "u1", "f1", "file", Map("bytes" -> "100")),
      event("e2", EventType.StorageReleased, "u1", "f1", "file", Map("bytes" -> "400"))
    )
    MetricsAggregator.dashboardSummary(events, "7d").storageUsedBytes shouldBe 0L
    MetricsAggregator.storageUsage(events, None).totalStorageBytes shouldBe 0L
  }

  it should "ignore events older than the requested window" in {
    val events = Seq(
      event("old", EventType.DocumentCreated, "u1", "d1", "document", at = now.minusSeconds(40L * 24 * 3600)),
      event("new", EventType.DocumentCreated, "u2", "d2", "document")
    )
    MetricsAggregator.dashboardSummary(events, "7d").totalEvents shouldBe 1L
    MetricsAggregator.dashboardSummary(events, "90d").totalEvents shouldBe 2L
  }

  "storageUsage" should "treat unparseable byte counts as zero" in {
    val events = Seq(
      event("e1", EventType.StorageAllocated, "u1", "f1", "file", Map("bytes" -> "not-a-number")),
      event("e2", EventType.StorageAllocated, "u1", "f2", "file", Map("bytes" -> "64"))
    )
    val usage = MetricsAggregator.storageUsage(events, Some("u1"))
    usage.totalStorageBytes shouldBe 64L
    usage.breakdownByType shouldBe Map("file" -> 64L)
  }

  "topContent" should "rank across both resource types and honour the limit" in {
    val events = Seq(
      event("e1", EventType.DocumentViewed, "u1", "d1", "document", Map("title" -> "Doc One")),
      event("e2", EventType.DocumentViewed, "u2", "d1", "document", Map("title" -> "Doc One")),
      event("e3", EventType.FileDownloaded, "u1", "f1", "file")
    )
    val all = MetricsAggregator.topContent(events, "all", "7d", 10)
    all.items.map(_.resourceId) shouldBe List("d1", "f1")
    all.items.head.title shouldBe "Doc One"
    all.items.head.uniqueUsers shouldBe 2L
    // resources without a title fall back to their id
    all.items.last.title shouldBe "f1"

    MetricsAggregator.topContent(events, "all", "7d", 1).items should have size 1
    MetricsAggregator.topContent(events, "files", "7d", 10).items.map(_.resourceId) shouldBe List("f1")
  }

  "exportData" should "emit newest-first rows with the wire field names" in {
    val older = event("e1", EventType.DocumentCreated, "u1", "d1", "document", at = now.minusSeconds(60))
    val newer = event("e2", EventType.DocumentViewed, "u2", "d1", "document", at = now.minusSeconds(10))
    val rows = MetricsAggregator.exportData(Seq(older, newer), "7d")

    rows.map(_("event_id")) shouldBe List("e2", "e1")
    rows.head.keySet shouldBe Set("event_id", "event_type", "user_id", "resource_id", "resource_type", "timestamp")
  }
