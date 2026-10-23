package com.otterworks.analytics.repository

import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.*
import org.slf4j.LoggerFactory

import scala.collection.mutable
import scala.concurrent.{ExecutionContext, Future}

/**
 * In-memory metrics repository that stores events in a process-local buffer.
 *
 * Useful for tests and local development where a live database is not
 * available. Aggregations are delegated to [[MetricsAggregator]] so its results
 * match the durable [[PostgresMetricsRepository]] exactly.
 *
 * The buffer is bounded to `maxEvents` (oldest evicted first) so per-query
 * snapshot and aggregation cost cannot grow without limit.
 */
class InMemoryMetricsRepository(
    config: PostgresConfig,
    maxEvents: Int = InMemoryMetricsRepository.DefaultMaxEvents
)(using ec: ExecutionContext) extends MetricsRepository:

  require(maxEvents > 0, "maxEvents must be positive")

  private val logger = LoggerFactory.getLogger(getClass)

  private val events = mutable.ArrayDeque.empty[AnalyticsEvent]
  private val lock = new Object

  private def snapshot(): Seq[AnalyticsEvent] = lock.synchronized(events.toSeq)

  def storeEvent(event: AnalyticsEvent): Future[Unit] = Future {
    lock.synchronized {
      events += event
      while events.size > maxEvents do events.removeHead()
    }
    logger.debug("Stored event {} of type {}", event.eventId, event.eventType)
  }

  def getDashboardSummary(period: String): Future[DashboardSummary] =
    Future(MetricsAggregator.dashboardSummary(snapshot(), period))

  def getUserActivity(userId: String): Future[UserActivity] =
    Future(MetricsAggregator.userActivity(snapshot(), userId))

  def getDocumentStats(documentId: String): Future[DocumentStats] =
    Future(MetricsAggregator.documentStats(snapshot(), documentId))

  def getTopContent(contentType: String, period: String, limit: Int): Future[TopContentResponse] =
    Future(MetricsAggregator.topContent(snapshot(), contentType, period, limit))

  def getActiveUsers(period: String): Future[ActiveUsersResponse] =
    Future(MetricsAggregator.activeUsers(snapshot(), period))

  def getStorageUsage(userId: Option[String]): Future[StorageUsageResponse] =
    Future(MetricsAggregator.storageUsage(snapshot(), userId))

  def getExportData(period: String): Future[List[Map[String, String]]] =
    Future(MetricsAggregator.exportData(snapshot(), period))

  def getEventCount: Future[Long] =
    Future(snapshot().size.toLong)

object InMemoryMetricsRepository:
  val DefaultMaxEvents: Int = 100000
