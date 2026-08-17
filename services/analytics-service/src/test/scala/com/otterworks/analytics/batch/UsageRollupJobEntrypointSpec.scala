package com.otterworks.analytics.batch

import com.otterworks.analytics.model.*
import com.otterworks.analytics.model.UsageRollupJsonProtocol.given
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Path, Paths}
import java.time.Instant

class UsageRollupJobEntrypointSpec extends AnyFlatSpec with Matchers:

  "UsageRollupJob.loadConfig" should "fall back to the bundled defaults when no env overrides are set" in {
    val config = UsageRollupJob.loadConfig()
    config.input shouldBe sys.env.getOrElse("ROLLUP_INPUT", UsageRollupJob.DefaultInput)
    config.output shouldBe sys.env.getOrElse("ROLLUP_OUTPUT", UsageRollupJob.DefaultOutput)
  }

  "UsageRollupJob.main" should "run the job end to end and write the default output document" in {
    val output: Path = Paths.get(UsageRollupJob.DefaultOutput)
    val preexisting = Files.exists(output)
    try
      UsageRollupJob.main(Array.empty)

      Files.exists(output) shouldBe true
      val report = new String(Files.readAllBytes(output), StandardCharsets.UTF_8)
        .parseJson.convertTo[UsageRollupReport]
      report.dayCount shouldBe 3L
      report.totalEvents shouldBe 165L
      report.source shouldBe UsageRollupJob.DefaultInput
    finally if !preexisting then Files.deleteIfExists(output): Unit
  }

  "UsageRollupJob.run" should "create missing parent directories for the output path" in {
    val dir = Files.createTempDirectory("usage-rollup-nested")
    val out = dir.resolve("reports/daily/rollup.json")
    try
      val report = UsageRollupJob.run(UsageRollupJob.Config(UsageRollupJob.DefaultInput, out.toString))
      Files.exists(out) shouldBe true
      new String(Files.readAllBytes(out), StandardCharsets.UTF_8)
        .parseJson.convertTo[UsageRollupReport].rollups shouldBe report.rollups
    finally
      Files.walk(dir).sorted(java.util.Comparator.reverseOrder()).forEach(p => Files.deleteIfExists(p): Unit)
  }

  "UsageRollupJob.buildReport" should "produce an empty window for an empty event set" in {
    val report = UsageRollupJob.buildReport(Seq.empty, "empty", Instant.parse("2024-03-04T00:00:00Z"))
    report.dayCount shouldBe 0L
    report.totalEvents shouldBe 0L
    report.windowStart shouldBe None
    report.windowEnd shouldBe None
    report.generatedAt shouldBe "2024-03-04T00:00:00Z"
  }
