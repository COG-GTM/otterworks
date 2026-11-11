package com.otterworks.analytics.batch

import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.MetricsAggregator

import java.time.{Instant, LocalDate, ZoneOffset}

/**
 * Pure aggregation logic for the nightly usage-rollup batch job.
 *
 * Groups a bulk collection of analytics events into one [[DailyUsageRollup]] per
 * calendar day (UTC). Deterministic: the same input always yields the same
 * output, ordered ascending by date. Kept free of any I/O so it is trivially
 * unit-testable and reusable by the future event-driven implementation.
 */
object UsageRollupAggregator:

  /** Roll a bulk collection of events up into per-day usage summaries. */
  def rollup(events: Seq[AnalyticsEvent]): List[DailyUsageRollup] =
    events
      .groupBy(e => dateOf(e.timestamp))
      .toList
      .sortBy(_._1)
      .map { case (date, dayEvents) => rollupDay(date, dayEvents) }

  private def rollupDay(date: LocalDate, dayEvents: Seq[AnalyticsEvent]): DailyUsageRollup =
    val allocated = storageBytes(dayEvents, EventType.StorageAllocated)
    val released = storageBytes(dayEvents, EventType.StorageReleased)
    DailyUsageRollup(
      date = date.toString,
      totalEvents = dayEvents.size.toLong,
      activeUsers = dayEvents.map(_.userId).distinct.size.toLong,
      documentsCreated = countOf(dayEvents, EventType.DocumentCreated),
      documentsViewed = countOf(dayEvents, EventType.DocumentViewed),
      documentsEdited = countOf(dayEvents, EventType.DocumentEdited),
      filesUploaded = countOf(dayEvents, EventType.FileUploaded),
      filesDownloaded = countOf(dayEvents, EventType.FileDownloaded),
      collabSessions = countOf(dayEvents, EventType.CollabSessionStarted),
      storageAllocatedBytes = allocated,
      storageReleasedBytes = released,
      netStorageBytes = allocated - released
    )

  private def countOf(events: Seq[AnalyticsEvent], eventType: String): Long =
    events.count(_.eventType == eventType).toLong

  private def storageBytes(events: Seq[AnalyticsEvent], eventType: String): Long =
    events
      .filter(_.eventType == eventType)
      .foldLeft(0L) { (acc, e) =>
        acc + MetricsAggregator.eventBytes(e)
      }

  private def dateOf(timestamp: Instant): LocalDate =
    timestamp.atZone(ZoneOffset.UTC).toLocalDate
