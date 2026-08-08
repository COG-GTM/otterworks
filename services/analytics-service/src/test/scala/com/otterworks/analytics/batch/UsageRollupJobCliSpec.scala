package com.otterworks.analytics.batch

import com.otterworks.analytics.model.*
import com.otterworks.analytics.model.UsageRollupJsonProtocol.given
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}

/** The CronJob entrypoint of the nightly batch job: config resolution and `main`. */
class UsageRollupJobCliSpec extends AnyFlatSpec with Matchers:

  "UsageRollupJob.loadConfig" should "resolve the environment overrides or the bundled defaults" in {
    val config = UsageRollupJob.loadConfig()

    config.input shouldBe sys.env.getOrElse("ROLLUP_INPUT", UsageRollupJob.DefaultInput)
    config.output shouldBe sys.env.getOrElse("ROLLUP_OUTPUT", UsageRollupJob.DefaultOutput)
  }

  "UsageRollupJob.main" should "write the report of the configured run" in {
    val config = UsageRollupJob.loadConfig()
    val output = Paths.get(config.output)
    try
      UsageRollupJob.main(Array.empty)

      Files.exists(output) shouldBe true
      val report = new String(Files.readAllBytes(output), StandardCharsets.UTF_8).parseJson.convertTo[UsageRollupReport]
      report.dayCount shouldBe report.rollups.size.toLong
      report.totalEvents shouldBe report.rollups.map(_.totalEvents).sum
      report.source shouldBe config.input
    finally Files.deleteIfExists(output): Unit
  }

  it should "create missing parent directories of the output path" in {
    val dir = Files.createTempDirectory("usage-rollup-cli-spec")
    val output = dir.resolve("nested/reports/rollup.json")
    try
      UsageRollupJob.run(UsageRollupJob.Config(UsageRollupJob.DefaultInput, output.toString))
      Files.exists(output) shouldBe true
    finally
      Files.walk(dir).sorted(java.util.Comparator.reverseOrder()).forEach(Files.deleteIfExists(_))
  }
