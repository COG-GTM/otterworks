package com.otterworks.analytics.repository

import com.otterworks.analytics.model.*

import scala.concurrent.Future

/** A metrics store whose every operation fails — drives the error paths of its callers. */
class UnavailableMetricsRepository(message: String = "metrics store unavailable") extends MetricsRepository:
  private def unavailable[A]: Future[A] = Future.failed(new RuntimeException(message))

  def storeEvent(event: AnalyticsEvent): Future[Unit] = unavailable
  def getDashboardSummary(period: String): Future[DashboardSummary] = unavailable
  def getUserActivity(userId: String): Future[UserActivity] = unavailable
  def getDocumentStats(documentId: String): Future[DocumentStats] = unavailable
  def getTopContent(contentType: String, period: String, limit: Int): Future[TopContentResponse] = unavailable
  def getActiveUsers(period: String): Future[ActiveUsersResponse] = unavailable
  def getStorageUsage(userId: Option[String]): Future[StorageUsageResponse] = unavailable
  def getExportData(period: String): Future[List[Map[String, String]]] = unavailable
  def getEventCount: Future[Long] = unavailable
