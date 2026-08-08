package com.otterworks.analytics.service

import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.MetricsRepository
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import scala.concurrent.ExecutionContext

/** Event counting (used by /health) and the default top-content page size. */
class AnalyticsServiceCountsSpec extends AnyFlatSpec with Matchers with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(50, Millis))
  given ExecutionContext = ExecutionContext.global

  private val testConfig = PostgresConfig(
    url = "jdbc:postgresql://localhost:5432/test",
    user = "test",
    password = "test",
    maxPoolSize = 2
  )

  private def createService(): AnalyticsService = AnalyticsService(MetricsRepository(testConfig))

  "AnalyticsService.getEventCount" should "count every tracked event" in {
    val service = createService()

    service.getEventCount.futureValue shouldBe 0L

    service.trackEvent(EventType.DocumentCreated, "user-1", "doc-1", "document", Map.empty).futureValue
    service.trackEvent(EventType.DocumentViewed, "user-1", "doc-1", "document", Map.empty).futureValue
    service.trackEvent(EventType.FileUploaded, "user-2", "file-1", "file", Map.empty).futureValue

    service.getEventCount.futureValue shouldBe 3L
  }

  "AnalyticsService.getTopContent" should "return at most ten items when no limit is given" in {
    val service = createService()
    for i <- 1 to 12 do
      for _ <- 1 to i do
        service.trackEvent(EventType.DocumentViewed, s"user-$i", f"doc-$i%02d", "document", Map.empty).futureValue

    val topDefault = service.getTopContent("document", "7d").futureValue

    topDefault.items should have size 10
    topDefault.items.head.resourceId shouldBe "doc-12"
    topDefault.items.map(_.resourceId) should not contain "doc-01"
  }

  it should "honour an explicit limit" in {
    val service = createService()
    for i <- 1 to 5 do
      for _ <- 1 to i do
        service.trackEvent(EventType.DocumentViewed, s"user-$i", s"doc-$i", "document", Map.empty).futureValue

    service.getTopContent("document", "7d", limit = 2).futureValue.items should have size 2
  }
