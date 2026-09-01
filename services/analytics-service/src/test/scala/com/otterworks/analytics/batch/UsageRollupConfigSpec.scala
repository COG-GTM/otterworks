package com.otterworks.analytics.batch

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.time.Instant

/** Covers the batch job's environment-driven configuration and empty-input report shape. */
class UsageRollupConfigSpec extends AnyFlatSpec with Matchers:

  "UsageRollupJob.loadConfig" should "fall back to the bundled seed and the default report path" in {
    // Guard: the assertion below is only meaningful when the overrides are unset.
    sys.env.get("ROLLUP_INPUT") shouldBe None
    sys.env.get("ROLLUP_OUTPUT") shouldBe None

    UsageRollupJob.loadConfig() shouldBe
      UsageRollupJob.Config("/seed/usage-events.ndjson", "rollup-output.json")
    UsageRollupJob.loadConfig().input shouldBe UsageRollupJob.DefaultInput
    UsageRollupJob.loadConfig().output shouldBe UsageRollupJob.DefaultOutput
  }

  "UsageRollupJob.buildReport" should "produce an empty window for an empty event set" in {
    val report = UsageRollupJob.buildReport(Seq.empty, "empty", Instant.parse("2024-03-04T02:00:00Z"))
    report.generatedAt shouldBe "2024-03-04T02:00:00Z"
    report.source shouldBe "empty"
    report.windowStart shouldBe None
    report.windowEnd shouldBe None
    report.dayCount shouldBe 0L
    report.totalEvents shouldBe 0L
    report.rollups shouldBe empty
  }

  "MarketSeeder.readResource" should "name the missing seed file when it is not on the classpath" in {
    val ex = the[IllegalArgumentException] thrownBy MarketSeeder.readResource("nope.csv")
    ex.getMessage shouldBe "Seed resource not found: /seed/market-series/nope.csv"
  }
