package com.otterworks.analytics.batch

import com.otterworks.analytics.model.UsageRollupReport
import com.otterworks.analytics.model.UsageRollupJsonProtocol.given
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}

/** Covers the CronJob entrypoint: env-driven config and the `main` wrapper. */
class UsageRollupJobMainSpec extends AnyFlatSpec with Matchers:

  "UsageRollupJob.loadConfig" should "use the bundled seed and default output when unconfigured" in {
    // ROLLUP_INPUT / ROLLUP_OUTPUT are only set by the CronJob manifest.
    assume(sys.env.get("ROLLUP_INPUT").isEmpty && sys.env.get("ROLLUP_OUTPUT").isEmpty)

    val config = UsageRollupJob.loadConfig()

    config shouldBe UsageRollupJob.Config(UsageRollupJob.DefaultInput, UsageRollupJob.DefaultOutput)
  }

  "UsageRollupJob.main" should "write the rollup report to the configured output path" in {
    val output = Paths.get(UsageRollupJob.DefaultOutput).toAbsolutePath
    try
      UsageRollupJob.main(Array.empty)

      Files.isRegularFile(output) shouldBe true
      val report = new String(Files.readAllBytes(output), StandardCharsets.UTF_8).parseJson
        .convertTo[UsageRollupReport]
      report.source shouldBe UsageRollupJob.DefaultInput
      report.dayCount should be > 0L
      report.totalEvents shouldBe report.rollups.map(_.totalEvents).sum
      report.windowStart shouldBe report.rollups.headOption.map(_.date)
      report.windowEnd shouldBe report.rollups.lastOption.map(_.date)
    finally Files.deleteIfExists(output): Unit
  }
