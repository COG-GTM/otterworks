package com.otterworks.analytics.repository

import com.otterworks.analytics.db.{AnalyticsDb, DailyMetric}
import com.otterworks.analytics.model.*
import org.slf4j.LoggerFactory
import slick.jdbc.GetResult
import slick.jdbc.PostgresProfile.api.*
import spray.json.*
import spray.json.DefaultJsonProtocol.*

import java.time.{Instant, ZoneOffset}
import scala.concurrent.{ExecutionContext, Future}

/**
 * Durable metrics repository backed by PostgreSQL via Slick.
 *
 * Every event is persisted to `analytics_events` and a daily aggregate rollup
 * (`analytics_daily_metrics`) is maintained transactionally on write. Query
 * responses are aggregated in SQL, bounded by period/limit and the caps in
 * [[MetricsAggregator.Limits]], so a request never loads the event log into
 * memory. They mirror [[MetricsAggregator]] (insertion id = first-seen order)
 * and are byte-for-byte identical to [[InMemoryMetricsRepository]] for the
 * same event set (see PostgresMetricsRepositorySpec).
 *
 * The event instant is stored as epoch-nanoseconds (UTC) so it round-trips
 * exactly, independent of database timestamp precision or server time zone —
 * important because analytics responses echo the ISO-8601 timestamp verbatim.
 *
 * This durable store is the "before" state for the analytics lakehouse
 * migration (S3 + Apache Iceberg); see the service README.
 */
class PostgresMetricsRepository(db: AnalyticsDb)(using ec: ExecutionContext) extends MetricsRepository:

  private val logger = LoggerFactory.getLogger(getClass)

  private def encodeMetadata(m: Map[String, String]): String = m.toJson.compactPrint
  private def decodeMetadata(s: String): Map[String, String] =
    if s == null || s.isEmpty then Map.empty else s.parseJson.convertTo[Map[String, String]]

  private def toEpochNanos(i: Instant): Long = i.getEpochSecond * 1000000000L + i.getNano
  private def fromEpochNanos(n: Long): Instant = Instant.ofEpochSecond(n / 1000000000L, n % 1000000000L)

  private given GetResult[DailyMetric] = GetResult { r =>
    DailyMetric(eventDate = r.nextString(), eventType = r.nextString(), eventCount = r.nextLong())
  }

  private def cutoffNanos(period: String): Long = toEpochNanos(MetricsAggregator.periodToCutoff(period))

  // `bytes` metadata is parsed like `String.toLong` in MetricsAggregator: an
  // optionally signed integer within the Long range, otherwise 0. Summed as
  // NUMERIC and narrowed with BigDecimal.toLong (low-order 64 bits), which
  // matches the wrapping Long fold of the in-memory aggregation.
  private val BytesLateral =
    """CROSS JOIN LATERAL (SELECT e.metadata::jsonb ->> 'bytes' AS raw) m
       CROSS JOIN LATERAL (SELECT CASE WHEN m.raw ~ '^[+-]?[0-9]+$' THEN
         CASE WHEN m.raw::numeric BETWEEN -9223372036854775808 AND 9223372036854775807
           THEN m.raw::numeric END END AS bytes) b"""

  private def wrapToLong(n: BigDecimal): Long = n.bigDecimal.longValue()

  private def iso(nanos: Long): String = fromEpochNanos(nanos).toString

  def storeEvent(event: AnalyticsEvent): Future[Unit] =
    val day = event.timestamp.atZone(ZoneOffset.UTC).toLocalDate.toString
    val occurred = toEpochNanos(event.timestamp)
    val insertEvent =
      sqlu"""INSERT INTO analytics_events
               (event_id, event_type, user_id, resource_id, resource_type, metadata, occurred_at)
             VALUES (${event.eventId}, ${event.eventType}, ${event.userId}, ${event.resourceId},
                     ${event.resourceType}, ${encodeMetadata(event.metadata)}, ${occurred})"""
    val upsertRollup =
      sqlu"""INSERT INTO analytics_daily_metrics (event_date, event_type, event_count)
             VALUES (${day}::date, ${event.eventType}, 1)
             ON CONFLICT (event_date, event_type)
             DO UPDATE SET event_count = analytics_daily_metrics.event_count + 1,
                           updated_at = NOW()"""
    db.database
      .run(DBIO.seq(insertEvent, upsertRollup).transactionally)
      .map { _ =>
        logger.debug("Stored event {} of type {}", event.eventId, event.eventType)
      }

  def getDashboardSummary(period: String): Future[DashboardSummary] =
    val cutoff = cutoffNanos(period)
    val windowed =
      sql"""SELECT COUNT(DISTINCT user_id),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.DocumentCreated}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.FileUploaded}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.CollabSessionStarted}),
                   COUNT(*)
            FROM analytics_events
            WHERE occurred_at > ${cutoff}""".as[(Long, Long, Long, Long, Long)].head
    val storage =
      sql"""SELECT COALESCE(SUM(b.bytes) FILTER (WHERE e.event_type = ${EventType.StorageAllocated}), 0)
                 - COALESCE(SUM(b.bytes) FILTER (WHERE e.event_type = ${EventType.StorageReleased}), 0)
            FROM analytics_events e #$BytesLateral
            WHERE e.event_type IN (${EventType.StorageAllocated}, ${EventType.StorageReleased})"""
        .as[BigDecimal].head
    db.database.run(windowed.zip(storage)).map { case ((users, docs, files, collab, total), storageNet) =>
      DashboardSummary(
        period = period,
        dailyActiveUsers = users,
        documentsCreated = docs,
        filesUploaded = files,
        storageUsedBytes = Math.max(0L, wrapToLong(storageNet)),
        collabSessions = collab,
        totalEvents = total
      )
    }

  def getUserActivity(userId: String): Future[UserActivity] =
    val counts =
      sql"""SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.DocumentCreated}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.DocumentViewed}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.DocumentEdited}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.FileUploaded}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.FileDownloaded})
            FROM analytics_events
            WHERE user_id = ${userId}""".as[(Long, Long, Long, Long, Long, Long)].head
    val recent =
      sql"""SELECT event_id, event_type, resource_id, resource_type, occurred_at
            FROM analytics_events
            WHERE user_id = ${userId}
            ORDER BY occurred_at DESC, id ASC
            LIMIT ${MetricsAggregator.Limits.RecentEvents}""".as[(String, String, String, String, Long)]
    db.database.run(counts.zip(recent)).map { case ((total, created, viewed, edited, uploaded, downloaded), rows) =>
      val summaries = rows.map { case (eventId, eventType, resourceId, resourceType, occurred) =>
        EventSummary(eventId, eventType, resourceId, resourceType, iso(occurred))
      }.toList
      UserActivity(
        userId = userId,
        totalEvents = total,
        documentsCreated = created,
        documentsViewed = viewed,
        documentsEdited = edited,
        filesUploaded = uploaded,
        filesDownloaded = downloaded,
        lastActiveAt = summaries.headOption.map(_.timestamp),
        recentEvents = summaries
      )
    }

  def getDocumentStats(documentId: String): Future[DocumentStats] =
    db.database.run(
      sql"""SELECT COUNT(*) FILTER (WHERE event_type = ${EventType.DocumentViewed}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.DocumentEdited}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.DocumentShared}),
                   COUNT(DISTINCT user_id) FILTER (WHERE event_type = ${EventType.DocumentViewed}),
                   MAX(occurred_at) FILTER (WHERE event_type = ${EventType.DocumentViewed}),
                   MAX(occurred_at) FILTER (WHERE event_type = ${EventType.DocumentEdited})
            FROM analytics_events
            WHERE resource_id = ${documentId}"""
        .as[(Long, Long, Long, Long, Option[Long], Option[Long])].head
    ).map { case (views, edits, shares, viewers, lastViewed, lastEdited) =>
      DocumentStats(
        documentId = documentId,
        views = views,
        edits = edits,
        shares = shares,
        uniqueViewers = viewers,
        lastViewedAt = lastViewed.map(iso),
        lastEditedAt = lastEdited.map(iso)
      )
    }

  def getTopContent(contentType: String, period: String, limit: Int): Future[TopContentResponse] =
    val cutoff = cutoffNanos(period)
    val (typeA, typeB) = contentType match
      case "documents" => ("document", "document")
      case "files"     => ("file", "file")
      case _           => ("document", "file")
    val bounded = MetricsAggregator.clampTopContentLimit(limit)
    db.database.run(
      sql"""WITH ranked AS (
              SELECT resource_id, COUNT(*) AS event_count, COUNT(DISTINCT user_id) AS unique_users,
                     MIN(id) AS first_id
              FROM analytics_events
              WHERE occurred_at > ${cutoff} AND resource_type IN (${typeA}, ${typeB})
              GROUP BY resource_id
              ORDER BY event_count DESC, first_id ASC
              LIMIT ${bounded}
            )
            SELECT r.resource_id, f.resource_type, f.metadata, r.event_count, r.unique_users
            FROM ranked r JOIN analytics_events f ON f.id = r.first_id
            ORDER BY r.event_count DESC, r.first_id ASC""".as[(String, String, String, Long, Long)]
    ).map { rows =>
      TopContentResponse(
        period = period,
        contentType = contentType,
        items = rows.map { case (resourceId, resourceType, metadata, eventCount, uniqueUsers) =>
          ContentItem(
            resourceId = resourceId,
            resourceType = resourceType,
            title = decodeMetadata(metadata).getOrElse("title", resourceId),
            eventCount = eventCount,
            uniqueUsers = uniqueUsers
          )
        }.toList
      )
    }

  def getActiveUsers(period: String): Future[ActiveUsersResponse] =
    val cutoff = cutoffNanos(period)
    val count =
      sql"""SELECT COUNT(DISTINCT user_id) FROM analytics_events WHERE occurred_at > ${cutoff}""".as[Long].head
    val top =
      sql"""SELECT user_id, COUNT(*) AS event_count, MAX(occurred_at), MIN(id) AS first_id
            FROM analytics_events
            WHERE occurred_at > ${cutoff}
            GROUP BY user_id
            ORDER BY event_count DESC, first_id ASC
            LIMIT ${MetricsAggregator.Limits.MaxActiveUsers}""".as[(String, Long, Long, Long)]
    db.database.run(count.zip(top)).map { case (total, rows) =>
      ActiveUsersResponse(
        period = period,
        count = total,
        users = rows.map { case (userId, eventCount, lastActive, _) =>
          ActiveUser(userId = userId, eventCount = eventCount, lastActiveAt = iso(lastActive))
        }.toList
      )
    }

  def getStorageUsage(userId: Option[String]): Future[StorageUsageResponse] =
    val (allUsers, uid) = (userId.isEmpty, userId.getOrElse(""))
    val totals =
      sql"""SELECT COALESCE(SUM(b.bytes) FILTER (WHERE e.event_type = ${EventType.StorageAllocated}), 0)
                 - COALESCE(SUM(b.bytes) FILTER (WHERE e.event_type = ${EventType.StorageReleased}), 0),
                   COUNT(*) FILTER (WHERE e.event_type = ${EventType.FileUploaded}),
                   COUNT(*) FILTER (WHERE e.event_type = ${EventType.DocumentCreated})
            FROM analytics_events e #$BytesLateral
            WHERE (${allUsers} OR e.user_id = ${uid})
              AND e.event_type IN (${EventType.StorageAllocated}, ${EventType.StorageReleased},
                                   ${EventType.FileUploaded}, ${EventType.DocumentCreated})"""
        .as[(BigDecimal, Long, Long)].head
    val breakdown =
      sql"""SELECT e.resource_type, COALESCE(SUM(b.bytes), 0)
            FROM analytics_events e #$BytesLateral
            WHERE (${allUsers} OR e.user_id = ${uid})
              AND e.event_type = ${EventType.StorageAllocated}
            GROUP BY e.resource_type""".as[(String, BigDecimal)]
    db.database.run(totals.zip(breakdown)).map { case ((net, files, docs), byType) =>
      StorageUsageResponse(
        userId = userId,
        totalStorageBytes = Math.max(0L, wrapToLong(net)),
        filesCount = files,
        documentsCount = docs,
        breakdownByType = byType.map { case (rt, sum) => rt -> wrapToLong(sum) }.toMap
      )
    }

  def getExportData(period: String): Future[List[Map[String, String]]] =
    val cutoff = cutoffNanos(period)
    db.database.run(
      sql"""SELECT event_id, event_type, user_id, resource_id, resource_type, occurred_at
            FROM analytics_events
            WHERE occurred_at > ${cutoff}
            ORDER BY occurred_at DESC, id ASC
            LIMIT ${MetricsAggregator.Limits.MaxExportRows}""".as[(String, String, String, String, String, Long)]
    ).map(_.map { case (eventId, eventType, userId, resourceId, resourceType, occurred) =>
      Map(
        "event_id" -> eventId,
        "event_type" -> eventType,
        "user_id" -> userId,
        "resource_id" -> resourceId,
        "resource_type" -> resourceType,
        "timestamp" -> iso(occurred)
      )
    }.toList)

  def getEventCount: Future[Long] =
    db.database.run(sql"SELECT COUNT(*) FROM analytics_events".as[Long].head)

  /** Read the persisted daily aggregate rollup (used by reconciliation checks). */
  def getDailyMetrics: Future[Seq[DailyMetric]] =
    db.database.run(
      sql"""SELECT to_char(event_date, 'YYYY-MM-DD'), event_type, event_count
            FROM analytics_daily_metrics ORDER BY event_date, event_type""".as[DailyMetric]
    )
