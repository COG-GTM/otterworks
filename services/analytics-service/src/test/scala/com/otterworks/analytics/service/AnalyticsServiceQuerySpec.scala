package com.otterworks.analytics.service

import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.MetricsRepository
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import scala.concurrent.{ExecutionContext, Future}

/** Query-side coverage of the service facade: top content, active users, storage, export. */
class AnalyticsServiceQuerySpec extends AnyFlatSpec with Matchers with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(50, Millis))
  given ExecutionContext = ExecutionContext.global

  private val testConfig = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)

  private def serviceWith(events: (String, String, String)*): AnalyticsService =
    val repo = MetricsRepository(testConfig)
    val service = AnalyticsService(repo)
    val tracked = Future.sequence(events.toList.map { case (eventType, userId, resourceId) =>
      service.trackEvent(eventType, userId, resourceId, "document", Map("bytes" -> "1024"))
    })
    tracked.futureValue
    service

  "getTopContent" should "rank resources by event count and honour the limit" in {
    val service = serviceWith(
      (EventType.DocumentViewed, "u1", "doc-hot"),
      (EventType.DocumentViewed, "u2", "doc-hot"),
      (EventType.DocumentViewed, "u1", "doc-cold")
    )
    val response = service.getTopContent("documents", "7d", 1).futureValue
    response.period shouldBe "7d"
    response.items.map(_.resourceId) shouldBe List("doc-hot")
    response.items.head.eventCount shouldBe 2L
    response.items.head.uniqueUsers shouldBe 2L

    service.getTopContent("documents", "7d", 10).futureValue.items.map(_.resourceId) should
      contain theSameElementsAs List("doc-hot", "doc-cold")
  }

  it should "default to the ten most active resources" in {
    val service = serviceWith((1 to 12).map(i => (EventType.DocumentViewed, "u1", s"doc-$i"))*)
    val response = service.getTopContent("documents", "7d").futureValue
    response.items should have size 10
  }

  "getActiveUsers" should "count the distinct users in the window" in {
    val service = serviceWith(
      (EventType.UserLoggedIn, "u1", "s1"),
      (EventType.UserLoggedIn, "u2", "s2"),
      (EventType.UserLoggedIn, "u1", "s3")
    )
    val response = service.getActiveUsers("daily").futureValue
    response.period shouldBe "daily"
    response.count shouldBe 2L
    response.users.map(_.userId) should contain theSameElementsAs List("u1", "u2")
    response.users.head.eventCount shouldBe 2L
  }

  "getStorageUsage" should "filter by user when one is supplied" in {
    val service = serviceWith(
      (EventType.StorageAllocated, "u1", "f1"),
      (EventType.StorageAllocated, "u2", "f2")
    )
    service.getStorageUsage(Some("u1")).futureValue.totalStorageBytes shouldBe 1024L
    service.getStorageUsage(None).futureValue.totalStorageBytes shouldBe 2048L
  }

  "getDocumentStats and getUserActivity" should "summarise a single resource and a single user" in {
    val service = serviceWith(
      (EventType.DocumentViewed, "u1", "doc-1"),
      (EventType.DocumentEdited, "u1", "doc-1"),
      (EventType.DocumentViewed, "u2", "doc-1")
    )
    val stats = service.getDocumentStats("doc-1").futureValue
    stats.views shouldBe 2L
    stats.edits shouldBe 1L
    stats.uniqueViewers shouldBe 2L

    val activity = service.getUserActivity("u1").futureValue
    activity.totalEvents shouldBe 2L
    activity.documentsViewed shouldBe 1L
    activity.recentEvents.map(_.eventType) should contain(EventType.DocumentEdited)
  }

  "exportReport" should "echo the requested format and count the exported records" in {
    val service = serviceWith(
      (EventType.DocumentViewed, "u1", "doc-1"),
      (EventType.FileUploaded, "u1", "file-1")
    )
    val report = service.exportReport("csv", "30d").futureValue
    report.format shouldBe "csv"
    report.period shouldBe "30d"
    report.recordCount shouldBe 2L
    report.data.map(_("resource_id")) should contain theSameElementsAs List("doc-1", "file-1")
    report.generatedAt should not be empty
  }

  it should "return an empty payload when nothing falls in the window" in {
    val report = AnalyticsService(MetricsRepository(testConfig)).exportReport("json", "7d").futureValue
    report.recordCount shouldBe 0L
    report.data shouldBe empty
  }
