package com.otterworks.analytics.repository

import com.otterworks.analytics.model.*
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.time.Instant

/** Boundary behaviour of the shared aggregations: unknown periods, clamping, bad metadata. */
class MetricsAggregatorEdgeSpec extends AnyFlatSpec with Matchers:

  private def event(
      eventType: String,
      userId: String = "u1",
      resourceId: String = "r1",
      resourceType: String = "document",
      metadata: Map[String, String] = Map.empty,
      timestamp: Instant = Instant.now().minusSeconds(60)
  ): AnalyticsEvent =
    AnalyticsEvent(
      eventId = s"$eventType-$userId-$resourceId-${timestamp.toEpochMilli}",
      eventType = eventType,
      userId = userId,
      resourceId = resourceId,
      resourceType = resourceType,
      metadata = metadata,
      timestamp = timestamp
    )

  "periodToCutoff" should "map each supported period to its window" in {
    val now = Instant.now()
    def days(period: String): Long = (now.getEpochSecond - MetricsAggregator.periodToCutoff(period).getEpochSecond) / 86400
    days("7d") shouldBe 7L
    days("30d") shouldBe 30L
    days("90d") shouldBe 90L
    days("daily") shouldBe 1L
    days("weekly") shouldBe 7L
    days("monthly") shouldBe 30L
  }

  it should "fall back to the seven-day window for an unrecognised period" in {
    val now = Instant.now()
    val cutoff = MetricsAggregator.periodToCutoff("since-the-dawn-of-time")
    (now.getEpochSecond - cutoff.getEpochSecond) / 86400 shouldBe 7L
  }

  "dashboardSummary" should "exclude events older than the requested window" in {
    val events = Seq(
      event(EventType.DocumentCreated),
      event(EventType.DocumentCreated, timestamp = Instant.now().minusSeconds(40L * 24 * 3600))
    )
    MetricsAggregator.dashboardSummary(events, "7d").documentsCreated shouldBe 1L
    MetricsAggregator.dashboardSummary(events, "90d").documentsCreated shouldBe 2L
  }

  it should "never report negative storage and ignore unparseable byte counts" in {
    val events = Seq(
      event(EventType.StorageAllocated, metadata = Map("bytes" -> "not-a-number")),
      event(EventType.StorageReleased, metadata = Map("bytes" -> "1024"))
    )
    MetricsAggregator.dashboardSummary(events, "7d").storageUsedBytes shouldBe 0L
    MetricsAggregator.storageUsage(events, None).totalStorageBytes shouldBe 0L
  }

  "storageUsage" should "scope the totals to a single user when one is given" in {
    val events = Seq(
      event(EventType.StorageAllocated, userId = "u1", metadata = Map("bytes" -> "2048")),
      event(EventType.StorageAllocated, userId = "u2", metadata = Map("bytes" -> "4096"))
    )
    MetricsAggregator.storageUsage(events, Some("u1")).totalStorageBytes shouldBe 2048L
    MetricsAggregator.storageUsage(events, None).totalStorageBytes shouldBe 6144L
    MetricsAggregator.storageUsage(events, None).breakdownByType shouldBe Map("document" -> 6144L)
  }

  "exportData" should "return the in-window events newest first with the CSV column keys" in {
    val older = event(EventType.DocumentViewed, timestamp = Instant.now().minusSeconds(3600))
    val newer = event(EventType.DocumentEdited, timestamp = Instant.now().minusSeconds(60))
    val rows = MetricsAggregator.exportData(Seq(older, newer), "7d")
    rows.map(_("event_type")) shouldBe List(EventType.DocumentEdited, EventType.DocumentViewed)
    rows.head.keySet shouldBe
      Set("event_id", "event_type", "user_id", "resource_id", "resource_type", "timestamp")
  }
