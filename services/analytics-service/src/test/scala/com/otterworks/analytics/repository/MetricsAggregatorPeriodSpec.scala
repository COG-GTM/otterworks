package com.otterworks.analytics.repository

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.time.Instant

/** `periodToCutoff` decides which events every aggregation sees, including for unknown periods. */
class MetricsAggregatorPeriodSpec extends AnyFlatSpec with Matchers:

  private val day = 24L * 3600

  /** The cutoff is relative to a fresh `Instant.now()`, so allow a small clock drift. */
  private def cutoffShouldBe(period: String, expectedSecondsBack: Long): Unit =
    val before = Instant.now().getEpochSecond
    val cutoff = MetricsAggregator.periodToCutoff(period).getEpochSecond
    val after = Instant.now().getEpochSecond
    withClue(s"period '$period': ") {
      cutoff should be >= before - expectedSecondsBack
      cutoff should be <= after - expectedSecondsBack
    }

  "periodToCutoff" should "map every supported period to its window" in {
    cutoffShouldBe("7d", 7 * day)
    cutoffShouldBe("30d", 30 * day)
    cutoffShouldBe("90d", 90 * day)
    cutoffShouldBe("daily", day)
    cutoffShouldBe("weekly", 7 * day)
    cutoffShouldBe("monthly", 30 * day)
  }

  it should "fall back to the 7-day window for an unrecognised period" in {
    cutoffShouldBe("fortnightly", 7 * day)
    cutoffShouldBe("", 7 * day)
  }
