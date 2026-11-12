package com.otterworks.analytics.service

import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.MetricsRepository
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.time.{Millis, Seconds, Span}

import scala.concurrent.ExecutionContext

class AnalyticsServiceSpec extends AnyFlatSpec with Matchers with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(100, Millis))
  given ExecutionContext = ExecutionContext.global

  private val User1 = "user-1"
  private val User2 = "user-2"
  private val Doc1 = "doc-1"
  private val Doc2 = "doc-2"
  private val File1 = "file-1"
  private val DocumentResource = "document"
  private val FileResource = "file"
  private val TitleKey = "title"
  private val SevenDays = "7d"
  private val PopularTitle = "Popular"

  private val testConfig = PostgresConfig(
    url = "jdbc:postgresql://localhost:5432/test",
    user = "test",
    password = "test",
    maxPoolSize = 2
  )

  private def createService(): AnalyticsService =
    val repo = MetricsRepository(testConfig)
    AnalyticsService(repo)

  "AnalyticsService.trackEvent" should "create and store an event" in {
    val service = createService()

    val result = service.trackEvent(
      EventType.DocumentCreated,
      User1,
      Doc1,
      DocumentResource,
      Map(TitleKey -> "Test Document")
    ).futureValue

    result.eventType shouldBe EventType.DocumentCreated
    result.userId shouldBe User1
    result.resourceId shouldBe Doc1
    result.eventId should not be empty
  }

  "AnalyticsService.getDashboardSummary" should "return aggregated metrics" in {
    val service = createService()

    // Track some events
    service.trackEvent(EventType.DocumentCreated, User1, Doc1, DocumentResource, Map.empty).futureValue
    service.trackEvent(EventType.DocumentCreated, User2, Doc2, DocumentResource, Map.empty).futureValue
    service.trackEvent(EventType.FileUploaded, User1, File1, FileResource, Map.empty).futureValue
    service.trackEvent(EventType.CollabSessionStarted, User1, "session-1", "session", Map.empty).futureValue

    val summary = service.getDashboardSummary(SevenDays).futureValue

    summary.period shouldBe SevenDays
    summary.dailyActiveUsers shouldBe 2
    summary.documentsCreated shouldBe 2
    summary.filesUploaded shouldBe 1
    summary.collabSessions shouldBe 1
    summary.totalEvents shouldBe 4
  }

  "AnalyticsService.getUserActivity" should "return activity for a specific user" in {
    val service = createService()

    service.trackEvent(EventType.DocumentCreated, User1, Doc1, DocumentResource, Map.empty).futureValue
    service.trackEvent(EventType.DocumentViewed, User1, Doc1, DocumentResource, Map.empty).futureValue
    service.trackEvent(EventType.FileUploaded, User1, File1, FileResource, Map.empty).futureValue
    service.trackEvent(EventType.DocumentCreated, User2, Doc2, DocumentResource, Map.empty).futureValue

    val activity = service.getUserActivity(User1).futureValue

    activity.userId shouldBe User1
    activity.totalEvents shouldBe 3
    activity.documentsCreated shouldBe 1
    activity.documentsViewed shouldBe 1
    activity.filesUploaded shouldBe 1
    activity.recentEvents.size shouldBe 3
  }

  "AnalyticsService.getDocumentStats" should "return document-level analytics" in {
    val service = createService()

    service.trackEvent(EventType.DocumentViewed, User1, Doc1, DocumentResource, Map.empty).futureValue
    service.trackEvent(EventType.DocumentViewed, User2, Doc1, DocumentResource, Map.empty).futureValue
    service.trackEvent(EventType.DocumentEdited, User1, Doc1, DocumentResource, Map.empty).futureValue
    service.trackEvent(EventType.DocumentShared, User1, Doc1, DocumentResource, Map.empty).futureValue

    val stats = service.getDocumentStats(Doc1).futureValue

    stats.documentId shouldBe Doc1
    stats.views shouldBe 2
    stats.edits shouldBe 1
    stats.shares shouldBe 1
    stats.uniqueViewers shouldBe 2
  }

  "AnalyticsService.getTopContent" should "return content ranked by activity" in {
    val service = createService()

    // doc-1 gets 3 events, doc-2 gets 1
    service.trackEvent(EventType.DocumentViewed, User1, Doc1, DocumentResource, Map(TitleKey -> PopularTitle)).futureValue
    service.trackEvent(EventType.DocumentViewed, User2, Doc1, DocumentResource, Map(TitleKey -> PopularTitle)).futureValue
    service.trackEvent(EventType.DocumentEdited, User1, Doc1, DocumentResource, Map(TitleKey -> PopularTitle)).futureValue
    service.trackEvent(EventType.DocumentViewed, User1, Doc2, DocumentResource, Map(TitleKey -> "Less Popular")).futureValue

    val response = service.getTopContent("documents", SevenDays, 10).futureValue

    response.items.size shouldBe 2
    response.items.head.resourceId shouldBe Doc1
    response.items.head.eventCount shouldBe 3
    response.items(1).resourceId shouldBe Doc2
  }

  "AnalyticsService.getActiveUsers" should "return users ranked by activity" in {
    val service = createService()

    service.trackEvent(EventType.DocumentViewed, User1, Doc1, DocumentResource, Map.empty).futureValue
    service.trackEvent(EventType.DocumentViewed, User1, Doc2, DocumentResource, Map.empty).futureValue
    service.trackEvent(EventType.DocumentViewed, User2, Doc1, DocumentResource, Map.empty).futureValue

    val response = service.getActiveUsers("daily").futureValue

    response.count shouldBe 2
    response.users.head.userId shouldBe User1
    response.users.head.eventCount shouldBe 2
  }

  "AnalyticsService.getStorageUsage" should "calculate storage metrics" in {
    val service = createService()

    service.trackEvent(EventType.StorageAllocated, User1, File1, FileResource, Map("bytes" -> "1024")).futureValue
    service.trackEvent(EventType.StorageAllocated, User1, "file-2", FileResource, Map("bytes" -> "2048")).futureValue
    service.trackEvent(EventType.FileUploaded, User1, File1, FileResource, Map.empty).futureValue

    val usage = service.getStorageUsage(Some(User1)).futureValue

    usage.userId shouldBe Some(User1)
    usage.totalStorageBytes shouldBe 3072
    usage.filesCount shouldBe 1
  }

  "AnalyticsService.exportReport" should "return event data for the period" in {
    val service = createService()

    service.trackEvent(EventType.DocumentCreated, User1, Doc1, DocumentResource, Map.empty).futureValue
    service.trackEvent(EventType.FileUploaded, User1, File1, FileResource, Map.empty).futureValue

    val report = service.exportReport("json", SevenDays).futureValue

    report.format shouldBe "json"
    report.period shouldBe SevenDays
    report.recordCount shouldBe 2
    report.data.size shouldBe 2
    report.data.head.keys should contain allOf("event_id", "event_type", "user_id")
  }
