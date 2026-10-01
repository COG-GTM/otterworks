package com.otterworks.analytics.service

import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.AnalyticsEvent
import com.otterworks.analytics.repository.MetricsRepository
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import java.time.Instant
import scala.concurrent.ExecutionContext.Implicits.global

class AnalyticsServiceQuerySpec extends AnyFlatSpec with Matchers with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(100, Millis))

  private val pgConfig = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)

  private def serviceWithEvents(): AnalyticsService =
    val repo = MetricsRepository(pgConfig)
    val service = AnalyticsService(repo)
    service.trackEvent("document.viewed", "u1", "doc-a", "document", Map("title" -> "A")).futureValue
    service.trackEvent("document.viewed", "u2", "doc-a", "document", Map.empty).futureValue
    service.trackEvent("document.viewed", "u1", "doc-b", "document", Map.empty).futureValue
    service.trackEvent("file.uploaded", "u1", "file-a", "file", Map("size_bytes" -> "1024")).futureValue
    service

  "AnalyticsService.getTopContent" should "rank documents by activity and honour the limit" in {
    val top = serviceWithEvents().getTopContent("documents", "30d", 1).futureValue
    top.items should have size 1
    top.items.head.resourceId shouldBe "doc-a"
    top.items.head.title shouldBe "A"
    top.items.head.eventCount shouldBe 2L
    top.items.head.uniqueUsers shouldBe 2L
    top.contentType shouldBe "documents"
    top.period shouldBe "30d"
  }

  it should "restrict the ranking to files when files are requested" in {
    val items = serviceWithEvents().getTopContent("files", "30d", 10).futureValue.items
    items.map(_.resourceId) shouldBe List("file-a")
    items.head.title shouldBe "file-a" // no title metadata: falls back to the resource id
  }

  it should "fall back to both resource types for an unrecognised content type" in {
    val items = serviceWithEvents().getTopContent("anything-else", "30d", 10).futureValue.items
    items.map(_.resourceId) should contain theSameElementsAs List("doc-a", "doc-b", "file-a")
    items.head.resourceId shouldBe "doc-a" // sorted by descending event count
  }

  it should "return an empty ranking for a repository with no events" in {
    val service = AnalyticsService(MetricsRepository(pgConfig))
    service.getTopContent("documents", "30d", 10).futureValue.items shouldBe empty
  }

  "AnalyticsService.exportReport" should "echo the requested format and period and count the records" in {
    val before = Instant.now()
    val report = serviceWithEvents().exportReport("csv", "30d").futureValue

    report.format shouldBe "csv"
    report.period shouldBe "30d"
    report.recordCount shouldBe 4L
    report.data should have size 4
    report.data.head.keys should contain allOf ("event_id", "event_type", "user_id", "timestamp")
    Instant.parse(report.generatedAt).isBefore(before) shouldBe false
  }

  it should "report zero records for a repository with no events" in {
    val service = AnalyticsService(MetricsRepository(pgConfig))
    val report = service.exportReport("json", "7d").futureValue
    report.recordCount shouldBe 0L
    report.data shouldBe empty
  }

  "AnalyticsService.getEventCount" should "count every stored event" in {
    val service = serviceWithEvents()
    service.getEventCount.futureValue shouldBe 4L
  }

  "AnalyticsService.getStorageUsage" should "scope the usage to a single user when one is given" in {
    val service = serviceWithEvents()
    val all = service.getStorageUsage(None).futureValue
    val scoped = service.getStorageUsage(Some("u1")).futureValue
    scoped.userId shouldBe Some("u1")
    all.userId shouldBe None
  }

  "AnalyticsService.trackEvent" should "return the event it persisted" in {
    val repo = MetricsRepository(pgConfig)
    val service = AnalyticsService(repo)
    val event: AnalyticsEvent = service.trackEvent("document.created", "u7", "d7", "document", Map("k" -> "v")).futureValue
    event.eventId should not be empty
    event.metadata shouldBe Map("k" -> "v")
    service.getDocumentStats("d7").futureValue.documentId shouldBe "d7"
  }
