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
 * responses are aggregated in SQL, bounded by the requested period and the
 * limits defined on [[MetricsAggregator]], so the event log is never loaded
 * into memory. Results are identical to [[InMemoryMetricsRepository]] (which
 * applies [[MetricsAggregator]]) for the same event set.
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

  private def iso(nanos: Long): String = fromEpochNanos(nanos).toString
  private def cutoffNanos(period: String): Long = toEpochNanos(MetricsAggregator.periodToCutoff(period))

  // Total of a set of signed Long byte counts; wraps on overflow like Long addition in MetricsAggregator.
  private def wrappedSum(total: BigDecimal): Long = total.bigDecimal.toBigInteger.longValue

  /**
   * `metadata.bytes` as a BIGINT, or 0 when absent or not a valid Long — the
   * SQL equivalent of `Try(metadata("bytes").toLong).getOrElse(0L)`.
   */
  private val BytesExpr =
    """CASE WHEN (metadata::jsonb ->> 'bytes') ~ '^[+-]?[0-9]+$'
         THEN CASE WHEN (metadata::jsonb ->> 'bytes')::numeric
                        BETWEEN -9223372036854775808 AND 9223372036854775807
                   THEN (metadata::jsonb ->> 'bytes')::bigint ELSE 0 END
         ELSE 0 END"""

  private def storageTotal(userId: Option[String]): DBIO[Long] =
    sql"""SELECT COALESCE(SUM(CASE WHEN event_type = ${EventType.StorageAllocated} THEN #$BytesExpr
                                   ELSE -(#$BytesExpr)::numeric END), 0)
          FROM analytics_events
          WHERE event_type IN (${EventType.StorageAllocated}, ${EventType.StorageReleased})
            AND (CAST(${userId} AS VARCHAR) IS NULL OR user_id = ${userId})"""
      .as[BigDecimal].head.map(wrappedSum)

  def getDashboardSummary(period: String): Future[DashboardSummary] =
    val cutoff = cutoffNanos(period)
    val windowed =
      sql"""SELECT COUNT(DISTINCT user_id),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.DocumentCreated}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.FileUploaded}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.CollabSessionStarted}),
                   COUNT(*)
            FROM analytics_events WHERE occurred_at > ${cutoff}""".as[(Long, Long, Long, Long, Long)].head
    db.database.run(windowed.zip(storageTotal(None))).map {
      case ((users, docs, files, collab, total), storage) =>
        DashboardSummary(
          period = period,
          dailyActiveUsers = users,
          documentsCreated = docs,
          filesUploaded = files,
          storageUsedBytes = Math.max(0L, storage),
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
            FROM analytics_events WHERE user_id = ${userId}""".as[(Long, Long, Long, Long, Long, Long)].head
    val recent =
      sql"""SELECT event_id, event_type, resource_id, resource_type, occurred_at
            FROM analytics_events WHERE user_id = ${userId}
            ORDER BY occurred_at DESC, id ASC
            LIMIT ${MetricsAggregator.RecentEventsLimit}""".as[(String, String, String, String, Long)]
    db.database.run(counts.zip(recent)).map {
      case ((total, created, viewed, edited, uploaded, downloaded), rows) =>
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
    val V = EventType.DocumentViewed
    val E = EventType.DocumentEdited
    db.database.run(
      sql"""SELECT COUNT(*) FILTER (WHERE event_type = ${V}),
                   COUNT(*) FILTER (WHERE event_type = ${E}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.DocumentShared}),
                   COUNT(DISTINCT user_id) FILTER (WHERE event_type = ${V}),
                   MAX(occurred_at) FILTER (WHERE event_type = ${V}),
                   MAX(occurred_at) FILTER (WHERE event_type = ${E})
            FROM analytics_events WHERE resource_id = ${documentId}"""
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
    val types = MetricsAggregator.topContentResourceTypes(contentType).toList.sorted
    val (typeA, typeB) = (types.head, types.last)
    val bounded = MetricsAggregator.boundedTopContentLimit(limit)
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
            SELECT r.resource_id, e.resource_type, e.metadata, r.event_count, r.unique_users
            FROM ranked r JOIN analytics_events e ON e.id = r.first_id
            ORDER BY r.event_count DESC, r.first_id ASC""".as[(String, String, String, Long, Long)]
    ).map { rows =>
      TopContentResponse(
        period = period,
        contentType = contentType,
        items = rows.map { case (resourceId, resourceType, metadata, count, users) =>
          ContentItem(
            resourceId = resourceId,
            resourceType = resourceType,
            title = decodeMetadata(metadata).getOrElse("title", resourceId),
            eventCount = count,
            uniqueUsers = users
          )
        }.toList
      )
    }

  def getActiveUsers(period: String): Future[ActiveUsersResponse] =
    val cutoff = cutoffNanos(period)
    val total =
      sql"""SELECT COUNT(DISTINCT user_id) FROM analytics_events
            WHERE occurred_at > ${cutoff}""".as[Long].head
    val users =
      sql"""SELECT user_id, COUNT(*) AS event_count, MAX(occurred_at)
            FROM analytics_events WHERE occurred_at > ${cutoff}
            GROUP BY user_id
            ORDER BY event_count DESC, MIN(id) ASC
            LIMIT ${MetricsAggregator.MaxActiveUsers}""".as[(String, Long, Long)]
    db.database.run(total.zip(users)).map { case (count, rows) =>
      ActiveUsersResponse(
        period = period,
        count = count,
        users = rows.map { case (userId, events, last) => ActiveUser(userId, events, iso(last)) }.toList
      )
    }

  def getStorageUsage(userId: Option[String]): Future[StorageUsageResponse] =
    val counts =
      sql"""SELECT COUNT(*) FILTER (WHERE event_type = ${EventType.FileUploaded}),
                   COUNT(*) FILTER (WHERE event_type = ${EventType.DocumentCreated})
            FROM analytics_events
            WHERE event_type IN (${EventType.FileUploaded}, ${EventType.DocumentCreated})
              AND (CAST(${userId} AS VARCHAR) IS NULL OR user_id = ${userId})""".as[(Long, Long)].head
    val breakdown =
      sql"""SELECT resource_type, SUM(#$BytesExpr)
            FROM analytics_events
            WHERE event_type = ${EventType.StorageAllocated}
              AND (CAST(${userId} AS VARCHAR) IS NULL OR user_id = ${userId})
            GROUP BY resource_type""".as[(String, BigDecimal)]
    db.database.run(storageTotal(userId).zip(counts).zip(breakdown)).map {
      case ((total, (files, docs)), byType) =>
        StorageUsageResponse(
          userId = userId,
          totalStorageBytes = Math.max(0L, total),
          filesCount = files,
          documentsCount = docs,
          breakdownByType = byType.map { case (rt, bytes) => rt -> wrappedSum(bytes) }.toMap
        )
    }

  def getExportData(period: String): Future[List[Map[String, String]]] =
    val cutoff = cutoffNanos(period)
    db.database.run(
      sql"""SELECT event_id, event_type, user_id, resource_id, resource_type, occurred_at
            FROM analytics_events WHERE occurred_at > ${cutoff}
            ORDER BY occurred_at DESC, id ASC
            LIMIT ${MetricsAggregator.MaxExportRows}""".as[(String, String, String, String, String, Long)]
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
