package com.otterworks.analytics.batch

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.time.LocalDate

/** Seed-resource resolution and the deterministic random walk. */
class MarketSeederSpec extends AnyFlatSpec with Matchers:

  "MarketSeeder.readResource" should "fail loudly for a missing seed file" in {
    val failure = the[IllegalArgumentException] thrownBy MarketSeeder.readResource("nope.csv")
    failure.getMessage should include("Seed resource not found")
  }

  "MarketSeeder.csvRows" should "drop the header and blank lines" in {
    val rows = MarketSeeder.csvRows(
      """series_code,name
        |SALMON_NOK_KG,Salmon
        |
        |USD_NOK,FX
        |""".stripMargin
    )
    rows.map(_.head) shouldBe List("SALMON_NOK_KG", "USD_NOK")
  }

  "MarketSeeder.nextWalkValue" should "use the default sigma for an unknown series and stay positive" in {
    val known = MarketSeeder.nextWalkValue("SALMON_NOK_KG", LocalDate.parse("2026-07-01"), BigDecimal(100))
    val unknown = MarketSeeder.nextWalkValue("MYSTERY_SERIES", LocalDate.parse("2026-07-01"), BigDecimal(100))

    known should be > BigDecimal(0)
    unknown should be > BigDecimal(0)
    // A collapsing series is floored rather than allowed to go non-positive.
    MarketSeeder.nextWalkValue("MYSTERY_SERIES", LocalDate.parse("2026-07-01"), BigDecimal("0.000001")) should
      be >= BigDecimal("0.01")
  }

  "MarketSeeder.walkExtension" should "return nothing when the series already reaches today" in {
    MarketSeeder.walkExtension(
      "USD_NOK", LocalDate.parse("2026-07-10"), BigDecimal("10.5"), LocalDate.parse("2026-07-10")) shouldBe empty
  }
