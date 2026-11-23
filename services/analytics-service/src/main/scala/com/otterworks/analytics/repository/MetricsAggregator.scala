package com.otterworks.analytics.repository

import com.otterworks.analytics.model.*

import java.time.Instant

/**
 * Pure, storage-agnostic analytics aggregations over a sequence of events.
 *
 * Both the in-memory and the durable PostgreSQL repositories derive their
 * query responses from these functions, so the two backends are guaranteed to
 * produce identical results for the same set of events. This is the
 * reconciliation baseline used when migrating the analytics store to an
 * S3 + Apache Iceberg lakehouse: the "before" (this durable store) and the
 * "after" (the lakehouse) must agree on every summary below.
 *
 * Events are expected in insertion order (oldest first); callers that read
 * from a database MUST return rows ordered by their monotonic insertion id so
 * that group-wise "first seen" semantics match the in-memory list.
 */
object MetricsAggregator:

  def dashboardSummary(events: Seq[AnalyticsEvent], period: String): DashboardSummary =
    val cutoff = periodToCutoff(period)
    val filtered = events.filter(_.timestamp.isAfter(cutoff))
    DashboardSummary(
      period = period,
      dailyActiveUsers = filtered.map(_.userId).distinct.size.toLong,
      documentsCreated = filtered.count(_.eventType == EventType.DocumentCreated).toLong,
      filesUploaded = filtered.count(_.eventType == EventType.FileUploaded).toLong,
      storageUsedBytes = Math.max(0L, events
        .filter(e => e.eventType == EventType.StorageAllocated || e.eventType == EventType.StorageReleased)
        .foldLeft(0L) { (acc, e) =>
          val bytes = scala.util.Try(e.metadata.getOrElse("bytes", "0").toLong).getOrElse(0L)
          if e.eventType == EventType.StorageAllocated then acc + bytes else acc - bytes
        }),
      collabSessions = filtered.count(_.eventType == EventType.CollabSessionStarted).toLong,
      totalEvents = filtered.size.toLong
    )

  def userActivity(events: Seq[AnalyticsEvent], userId: String): UserActivity =
    val userEvents = events.filter(_.userId == userId)
    val recent = userEvents.sortBy(_.timestamp)(using Ordering[Instant].reverse).take(20)
    UserActivity(
      userId = userId,
      totalEvents = userEvents.size.toLong,
      documentsCreated = userEvents.count(_.eventType == EventType.DocumentCreated).toLong,
      documentsViewed = userEvents.count(_.eventType == EventType.DocumentViewed).toLong,
      documentsEdited = userEvents.count(_.eventType == EventType.DocumentEdited).toLong,
      filesUploaded = userEvents.count(_.eventType == EventType.FileUploaded).toLong,
      filesDownloaded = userEvents.count(_.eventType == EventType.FileDownloaded).toLong,
      lastActiveAt = recent.headOption.map(_.timestamp.toString),
      recentEvents = recent.map(e =>
        EventSummary(
          eventId = e.eventId,
          eventType = e.eventType,
          resourceId = e.resourceId,
          resourceType = e.resourceType,
          timestamp = e.timestamp.toString
        )
      ).toList
    )

  def documentStats(events: Seq[AnalyticsEvent], documentId: String): DocumentStats =
    val docEvents = events.filter(_.resourceId == documentId)
    val views = docEvents.filter(_.eventType == EventType.DocumentViewed)
    val edits = docEvents.filter(_.eventType == EventType.DocumentEdited)
    val shares = docEvents.filter(_.eventType == EventType.DocumentShared)
    DocumentStats(
      documentId = documentId,
      views = views.size.toLong,
      edits = edits.size.toLong,
      shares = shares.size.toLong,
      uniqueViewers = views.map(_.userId).distinct.size.toLong,
      lastViewedAt = views.sortBy(_.timestamp)(using Ordering[Instant].reverse).headOption.map(_.timestamp.toString),
      lastEditedAt = edits.sortBy(_.timestamp)(using Ordering[Instant].reverse).headOption.map(_.timestamp.toString)
    )

  /** The user who first recorded `document.created` for the document, if any. */
  def documentCreator(events: Seq[AnalyticsEvent], documentId: String): Option[String] =
    events.find(e => e.resourceId == documentId && e.eventType == EventType.DocumentCreated).map(_.userId)

  def topContent(events: Seq[AnalyticsEvent], contentType: String, period: String, limit: Int): TopContentResponse =
    val cutoff = periodToCutoff(period)
    val resourceTypeFilter = contentType match
      case "documents" => Set("document")
      case "files"     => Set("file")
      case _           => Set("document", "file")

    val filtered = events
      .filter(e => e.timestamp.isAfter(cutoff) && resourceTypeFilter.contains(e.resourceType))

    val grouped = filtered.groupBy(_.resourceId)
    val items = grouped.toList
      .map { case (resourceId, resourceEvents) =>
        ContentItem(
          resourceId = resourceId,
          resourceType = resourceEvents.head.resourceType,
          title = resourceEvents.head.metadata.getOrElse("title", resourceId),
          eventCount = resourceEvents.size.toLong,
          uniqueUsers = resourceEvents.map(_.userId).distinct.size.toLong
        )
      }
      .sortBy(-_.eventCount)
      .take(limit)

    TopContentResponse(
      period = period,
      contentType = contentType,
      items = items
    )

  def activeUsers(events: Seq[AnalyticsEvent], period: String): ActiveUsersResponse =
    val cutoff = periodToCutoff(period)
    val filtered = events.filter(_.timestamp.isAfter(cutoff))
    val grouped = filtered.groupBy(_.userId)
    val users = grouped.toList
      .map { case (userId, userEvents) =>
        ActiveUser(
          userId = userId,
          eventCount = userEvents.size.toLong,
          lastActiveAt = userEvents.maxBy(_.timestamp).timestamp.toString
        )
      }
      .sortBy(-_.eventCount)

    ActiveUsersResponse(
      period = period,
      count = users.size.toLong,
      users = users
    )

  def storageUsage(events: Seq[AnalyticsEvent], userId: Option[String]): StorageUsageResponse =
    val filtered = userId match
      case Some(uid) => events.filter(_.userId == uid)
      case None      => events

    val storageEvents = filtered.filter(e =>
      e.eventType == EventType.StorageAllocated || e.eventType == EventType.StorageReleased
    )

    val totalBytes = storageEvents.foldLeft(0L) { (acc, e) =>
      val bytes = scala.util.Try(e.metadata.getOrElse("bytes", "0").toLong).getOrElse(0L)
      if e.eventType == EventType.StorageAllocated then acc + bytes else acc - bytes
    }

    val filesCount = filtered.count(_.eventType == EventType.FileUploaded).toLong
    val docsCount = filtered.count(_.eventType == EventType.DocumentCreated).toLong

    val breakdownByType = filtered
      .filter(e => e.eventType == EventType.StorageAllocated)
      .groupBy(_.resourceType)
      .map { case (rt, evts) =>
        rt -> evts.flatMap(_.metadata.get("bytes").flatMap(s => scala.util.Try(s.toLong).toOption)).sum
      }
      .toMap

    StorageUsageResponse(
      userId = userId,
      totalStorageBytes = Math.max(0L, totalBytes),
      filesCount = filesCount,
      documentsCount = docsCount,
      breakdownByType = breakdownByType
    )

  def exportData(events: Seq[AnalyticsEvent], period: String): List[Map[String, String]] =
    val cutoff = periodToCutoff(period)
    events
      .filter(_.timestamp.isAfter(cutoff))
      .sortBy(_.timestamp)(using Ordering[Instant].reverse)
      .map { e =>
        Map(
          "event_id" -> e.eventId,
          "event_type" -> e.eventType,
          "user_id" -> e.userId,
          "resource_id" -> e.resourceId,
          "resource_type" -> e.resourceType,
          "timestamp" -> e.timestamp.toString
        )
      }
      .toList

  def periodToCutoff(period: String): Instant =
    val now = Instant.now()
    period match
      case "7d"      => now.minusSeconds(7L * 24 * 3600)
      case "30d"     => now.minusSeconds(30L * 24 * 3600)
      case "90d"     => now.minusSeconds(90L * 24 * 3600)
      case "daily"   => now.minusSeconds(24L * 3600)
      case "weekly"  => now.minusSeconds(7L * 24 * 3600)
      case "monthly" => now.minusSeconds(30L * 24 * 3600)
      case _         => now.minusSeconds(7L * 24 * 3600)
