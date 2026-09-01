package com.otterworks.analytics.service

import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.repository.MetricsRepository
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import scala.concurrent.ExecutionContext

/** Service-level defaults that the HTTP layer always passes explicitly. */
class AnalyticsServiceDefaultsSpec extends AnyFlatSpec with Matchers with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(50, Millis))
  given ExecutionContext = ExecutionContext.global

  private def serviceWith(events: Int): AnalyticsService =
    val service = AnalyticsService(MetricsRepository(PostgresConfig("", "", "", 1)))
    (1 to events).foreach { i =>
      service.trackEvent("document.viewed", s"user-$i", s"doc-$i", "document", Map.empty).futureValue
    }
    service

  "getTopContent" should "default the limit to ten items" in {
    val service = serviceWith(12)

    service.getTopContent("documents", "7d").futureValue.items should have size 10
    service.getTopContent("documents", "7d", 12).futureValue.items should have size 12
  }

  "getEventCount" should "report everything tracked so far" in {
    serviceWith(3).getEventCount.futureValue shouldBe 3L
  }
