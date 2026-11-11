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
 * Events are expected in insertion order (oldest first). The PostgreSQL store
 * computes the same results in SQL; it reproduces the "first seen" and
 * tie-breaking semantics here by ordering on the monotonic insertion id.
 *
 * Response sizes are bounded: top-content `limit` is clamped to
 * [[MaxTopContentLimit]], active-users lists at most [[MaxActiveUsers]] users
 * (`count` still reports the total), and exports return at most
 * [[MaxExportRows]] rows (newest first) from a window of at most 90 days.
 */
object MetricsAggregator:

  /** Upper bound on `limit` for top-content listings. */
  val MaxTopContentLimit: Int = 100
  /** Upper bound on the number of users listed by active-users. */
  val MaxActiveUsers: Int = 1000
  /** Upper bound on the number of rows returned by a single export. */
  val MaxExportRows: Int = 10000
  /** Number of recent events included in a user activity feed. */
  val RecentEventsLimit: Int = 20

  /** Clamp a caller-supplied top-content limit into `[0, MaxTopContentLimit]`. */
  def boundedTopContentLimit(limit: Int): Int = Math.max(0, Math.min(limit, MaxTopContentLimit))

  private val ByteCount = "[+-]?0*[0-9]{1,19}".r

  /** A `bytes` metadata value as a Long: ASCII decimal digits (leading zeros allowed), otherwise 0. */
  def parseBytes(raw: String): Long =
    if ByteCount.matches(raw) then raw.toLongOption.getOrElse(0L) else 0L

  /** The `bytes` metadata of an event, or 0 when absent or invalid. */
  def eventBytes(e: AnalyticsEvent): Long = e.metadata.get("bytes").fold(0L)(parseBytes)

  /** Resource types included in a top-content listing for the given content type. */
  def topContentResourceTypes(contentType: String): Set[String] = contentType match
    case "documents" => Set("document")
    case "files"     => Set("file")
    case _           => Set("document", "file")

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
          val bytes = eventBytes(e)
          if e.eventType == EventType.StorageAllocated then acc + bytes else acc - bytes
        }),
      collabSessions = filtered.count(_.eventType == EventType.CollabSessionStarted).toLong,
      totalEvents = filtered.size.toLong
    )

  def userActivity(events: Seq[AnalyticsEvent], userId: String): UserActivity =
    val userEvents = events.filter(_.userId == userId)
    val recent = userEvents.sortBy(_.timestamp)(using Ordering[Instant].reverse).take(RecentEventsLimit)
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

  def topContent(events: Seq[AnalyticsEvent], contentType: String, period: String, limit: Int): TopContentResponse =
    val cutoff = periodToCutoff(period)
    val resourceTypeFilter = topContentResourceTypes(contentType)

    val filtered = events.zipWithIndex
      .filter { case (e, _) => e.timestamp.isAfter(cutoff) && resourceTypeFilter.contains(e.resourceType) }

    // Ties on eventCount are broken by first appearance so the ordering is deterministic.
    val grouped = filtered.groupBy(_._1.resourceId)
    val items = grouped.toList
      .map { case (resourceId, indexed) =>
        val resourceEvents = indexed.map(_._1)
        val item = ContentItem(
          resourceId = resourceId,
          resourceType = resourceEvents.head.resourceType,
          title = resourceEvents.head.metadata.getOrElse("title", resourceId),
          eventCount = resourceEvents.size.toLong,
          uniqueUsers = resourceEvents.map(_.userId).distinct.size.toLong
        )
        (item, indexed.head._2)
      }
      .sortBy { case (item, firstIndex) => (-item.eventCount, firstIndex) }
      .map(_._1)
      .take(boundedTopContentLimit(limit))

    TopContentResponse(
      period = period,
      contentType = contentType,
      items = items
    )

  def activeUsers(events: Seq[AnalyticsEvent], period: String): ActiveUsersResponse =
    val cutoff = periodToCutoff(period)
    val filtered = events.zipWithIndex.filter(_._1.timestamp.isAfter(cutoff))
    val grouped = filtered.groupBy(_._1.userId)
    val users = grouped.toList
      .map { case (userId, indexed) =>
        val userEvents = indexed.map(_._1)
        val user = ActiveUser(
          userId = userId,
          eventCount = userEvents.size.toLong,
          lastActiveAt = userEvents.maxBy(_.timestamp).timestamp.toString
        )
        (user, indexed.head._2)
      }
      .sortBy { case (user, firstIndex) => (-user.eventCount, firstIndex) }
      .map(_._1)

    ActiveUsersResponse(
      period = period,
      count = users.size.toLong,
      users = users.take(MaxActiveUsers)
    )

  def storageUsage(events: Seq[AnalyticsEvent], userId: Option[String]): StorageUsageResponse =
    val filtered = userId match
      case Some(uid) => events.filter(_.userId == uid)
      case None      => events

    val storageEvents = filtered.filter(e =>
      e.eventType == EventType.StorageAllocated || e.eventType == EventType.StorageReleased
    )

    val totalBytes = storageEvents.foldLeft(0L) { (acc, e) =>
      val bytes = eventBytes(e)
      if e.eventType == EventType.StorageAllocated then acc + bytes else acc - bytes
    }

    val filesCount = filtered.count(_.eventType == EventType.FileUploaded).toLong
    val docsCount = filtered.count(_.eventType == EventType.DocumentCreated).toLong

    val breakdownByType = filtered
      .filter(e => e.eventType == EventType.StorageAllocated)
      .groupBy(_.resourceType)
      .map { case (rt, evts) =>
        rt -> evts.map(eventBytes).sum
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
      .take(MaxExportRows)
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
