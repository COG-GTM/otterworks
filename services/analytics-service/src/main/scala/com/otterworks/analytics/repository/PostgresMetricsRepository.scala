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
 * responses are derived by loading the durable event log (in insertion order)
 * and applying [[MetricsAggregator]], so results are byte-for-byte identical to
 * [[InMemoryMetricsRepository]] for the same event set.
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

  private given GetResult[AnalyticsEvent] = GetResult { r =>
    AnalyticsEvent(
      eventId = r.nextString(),
      eventType = r.nextString(),
      userId = r.nextString(),
      resourceId = r.nextString(),
      resourceType = r.nextString(),
      metadata = decodeMetadata(r.nextString()),
      timestamp = fromEpochNanos(r.nextLong())
    )
  }

  private given GetResult[DailyMetric] = GetResult { r =>
    DailyMetric(eventDate = r.nextString(), eventType = r.nextString(), eventCount = r.nextLong())
  }

  /** Load the full event log in insertion order (matches the in-memory buffer). */
  private def loadAll(): Future[Seq[AnalyticsEvent]] =
    db.database.run(
      sql"""SELECT event_id, event_type, user_id, resource_id, resource_type, metadata, occurred_at
            FROM analytics_events ORDER BY id ASC""".as[AnalyticsEvent]
    )

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
    loadAll().map(MetricsAggregator.dashboardSummary(_, period))

  def getUserActivity(userId: String): Future[UserActivity] =
    loadAll().map(MetricsAggregator.userActivity(_, userId))

  def getDocumentStats(documentId: String): Future[DocumentStats] =
    loadAll().map(MetricsAggregator.documentStats(_, documentId))

  def getDocumentCreator(documentId: String): Future[Option[String]] =
    loadAll().map(MetricsAggregator.documentCreator(_, documentId))

  def getTopContent(contentType: String, period: String, limit: Int): Future[TopContentResponse] =
    loadAll().map(MetricsAggregator.topContent(_, contentType, period, limit))

  def getActiveUsers(period: String): Future[ActiveUsersResponse] =
    loadAll().map(MetricsAggregator.activeUsers(_, period))

  def getStorageUsage(userId: Option[String]): Future[StorageUsageResponse] =
    loadAll().map(MetricsAggregator.storageUsage(_, userId))

  def getExportData(period: String): Future[List[Map[String, String]]] =
    loadAll().map(MetricsAggregator.exportData(_, period))

  def getEventCount: Future[Long] =
    db.database.run(sql"SELECT COUNT(*) FROM analytics_events".as[Long].head)

  /** Read the persisted daily aggregate rollup (used by reconciliation checks). */
  def getDailyMetrics: Future[Seq[DailyMetric]] =
    db.database.run(
      sql"""SELECT to_char(event_date, 'YYYY-MM-DD'), event_type, event_count
            FROM analytics_daily_metrics ORDER BY event_date, event_type""".as[DailyMetric]
    )
