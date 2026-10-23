package com.otterworks.analytics.repository

import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.model.*
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.time.Instant
import scala.concurrent.{Await, ExecutionContext}
import scala.concurrent.duration.*

/** Response caps and the bounded in-memory buffer (both storage backends share these caps). */
class MetricsBoundsSpec extends AnyFlatSpec with Matchers with ScalaFutures:

  given ExecutionContext = ExecutionContext.global

  private val now = Instant.now().minusSeconds(60)
  private def ev(i: Int, user: String, resource: String, at: Instant = now): AnalyticsEvent =
    AnalyticsEvent(f"e$i%06d", EventType.DocumentViewed, user, resource, "document", Map.empty, at)

  private def many(n: Int): Seq[AnalyticsEvent] =
    (1 to n).map(i => ev(i, s"user-${i % 1500}", s"doc-${i % 250}", now.minusMillis(i.toLong)))

  "clampTopContentLimit" should "bound the requested page size to [1, MaxTopContent]" in {
    MetricsAggregator.clampTopContentLimit(-5) shouldBe 1
    MetricsAggregator.clampTopContentLimit(0) shouldBe 1
    MetricsAggregator.clampTopContentLimit(10) shouldBe 10
    MetricsAggregator.clampTopContentLimit(Int.MaxValue) shouldBe MetricsAggregator.Limits.MaxTopContent
  }

  "MetricsAggregator" should "cap top-content, active-user and export result sizes" in {
    val events = many(MetricsAggregator.Limits.MaxExportRows + 500)

    MetricsAggregator.topContent(events, "all", "7d", 10_000).items should have size
      MetricsAggregator.Limits.MaxTopContent

    val active = MetricsAggregator.activeUsers(events, "7d")
    active.count shouldBe 1500
    active.users should have size MetricsAggregator.Limits.MaxActiveUsers

    val export = MetricsAggregator.exportData(events, "7d")
    export should have size MetricsAggregator.Limits.MaxExportRows
    export.head("event_id") shouldBe "e000001" // newest first
  }

  it should "cap a user's recent events" in {
    val events = (1 to 50).map(i => ev(i, "user-1", "doc-1", now.minusSeconds(i.toLong)))
    val activity = MetricsAggregator.userActivity(events, "user-1")
    activity.totalEvents shouldBe 50
    activity.recentEvents should have size MetricsAggregator.Limits.RecentEvents
  }

  it should "break event-count ties by first-seen order" in {
    val events = Seq(ev(1, "user-b", "doc-b"), ev(2, "user-a", "doc-a"), ev(3, "user-c", "doc-c"), ev(4, "user-c", "doc-c"))
    MetricsAggregator.activeUsers(events, "7d").users.map(_.userId) shouldBe List("user-c", "user-b", "user-a")
    MetricsAggregator.topContent(events, "all", "7d", 10).items.map(_.resourceId) shouldBe List("doc-c", "doc-b", "doc-a")
  }

  it should "exclude events outside the requested period" in {
    val old = ev(1, "user-old", "doc-old", Instant.now().minusSeconds(8L * 24 * 3600))
    val events = Seq(old, ev(2, "user-new", "doc-new"))
    MetricsAggregator.exportData(events, "7d").map(_("event_id")) shouldBe List("e000002")
    MetricsAggregator.activeUsers(events, "7d").count shouldBe 1
  }

  "parseBytes" should "accept only signed ASCII integers within the Long range" in {
    def p(v: String) = MetricsAggregator.parseBytes(Map("bytes" -> v))
    p("42") shouldBe Some(42L)
    p("+42") shouldBe Some(42L)
    p("-5") shouldBe Some(-5L)
    p(Long.MaxValue.toString) shouldBe Some(Long.MaxValue)
    p("9223372036854775808") shouldBe None
    p("abc") shouldBe None
    p("\u0661\u0662") shouldBe None
    MetricsAggregator.parseBytes(Map.empty) shouldBe None
  }

  "InMemoryMetricsRepository" should "evict the oldest events beyond maxEvents" in {
    val repo = new InMemoryMetricsRepository(PostgresConfig("", "", "", 1), maxEvents = 5)
    (1 to 8).foreach(i => Await.result(repo.storeEvent(ev(i, "user-1", "doc-1", now.plusMillis(i.toLong))), 5.seconds))

    repo.getEventCount.futureValue shouldBe 5
    repo.getExportData("7d").futureValue.map(_("event_id")) shouldBe
      List("e000008", "e000007", "e000006", "e000005", "e000004")
  }

  it should "reject a non-positive maxEvents" in {
    an[IllegalArgumentException] should be thrownBy
      new InMemoryMetricsRepository(PostgresConfig("", "", "", 1), maxEvents = 0)
  }
