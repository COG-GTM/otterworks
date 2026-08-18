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

  "UsageRollupJob.main" should "run the job end to end and write the configured output document" in {
    // Honour ROLLUP_OUTPUT/ROLLUP_INPUT exactly as the job does, and never clobber an existing
    // report: back it up and restore it afterwards.
    val config = UsageRollupJob.loadConfig()
    val output: Path = Paths.get(config.output)
    val backup = Option.when(Files.exists(output))(Files.readAllBytes(output))
    val expected = UsageRollupJob.buildReport(
      EventLoader.load(config.input), config.input, Instant.parse("2024-03-04T00:00:00Z"))
    try
      UsageRollupJob.main(Array.empty)

      Files.exists(output) shouldBe true
      val report = new String(Files.readAllBytes(output), StandardCharsets.UTF_8)
        .parseJson.convertTo[UsageRollupReport]
      report.dayCount shouldBe expected.dayCount
      report.totalEvents shouldBe expected.totalEvents
      report.rollups shouldBe expected.rollups
      report.source shouldBe config.input
    finally
      backup.fold(Files.deleteIfExists(output): Unit)(bytes => Files.write(output, bytes): Unit)
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
