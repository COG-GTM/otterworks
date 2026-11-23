package com.otterworks.analytics.repository

import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.*

import scala.concurrent.{ExecutionContext, Future}

/**
 * Metrics repository abstraction for the analytics service.
 *
 * Two implementations exist:
 *  - [[InMemoryMetricsRepository]] — an ephemeral, process-local store used for
 *    tests and local development.
 *  - [[PostgresMetricsRepository]] — the durable store backed by PostgreSQL via
 *    Slick. This is the golden-app default and the "before" state for the
 *    S3 + Apache Iceberg lakehouse migration (see README).
 *
 * Both derive their query responses from [[MetricsAggregator]], guaranteeing
 * identical results for identical event sets — the reconciliation baseline.
 */
trait MetricsRepository:
  def storeEvent(event: AnalyticsEvent): Future[Unit]
  def getDashboardSummary(period: String): Future[DashboardSummary]
  def getUserActivity(userId: String): Future[UserActivity]
  def getDocumentStats(documentId: String): Future[DocumentStats]
  def getDocumentCreator(documentId: String): Future[Option[String]]
  def getTopContent(contentType: String, period: String, limit: Int): Future[TopContentResponse]
  def getActiveUsers(period: String): Future[ActiveUsersResponse]
  def getStorageUsage(userId: Option[String]): Future[StorageUsageResponse]
  def getExportData(period: String): Future[List[Map[String, String]]]
  def getEventCount: Future[Long]

object MetricsRepository:
  /**
   * Construct the default (in-memory) repository.
   *
   * Retained for source-compatibility with call sites (and tests) that
   * previously constructed `MetricsRepository(config)` directly. The durable
   * PostgreSQL backend is selected explicitly in `Main` based on configuration.
   */
  def apply(config: PostgresConfig)(using ec: ExecutionContext): MetricsRepository =
    new InMemoryMetricsRepository(config)
