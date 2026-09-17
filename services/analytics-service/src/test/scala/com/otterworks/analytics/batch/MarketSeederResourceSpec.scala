package com.otterworks.analytics.batch

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

/** The seeder reads its baseline from bundled resources; a missing one must fail loudly. */
class MarketSeederResourceSpec extends AnyFlatSpec with Matchers:

  "MarketSeeder.readResource" should "fail with the resolved resource path when the file is missing" in {
    val ex = intercept[IllegalArgumentException](MarketSeeder.readResource("not-a-seed-file.csv"))

    ex.getMessage should include("not-a-seed-file.csv")
    ex.getMessage should include("Seed resource not found")
  }

  it should "read a bundled seed resource as UTF-8 text" in {
    val content = MarketSeeder.readResource("series.csv")

    content.linesIterator.next() should include("series_code")
    content should include("SALMON_NOK_KG")
  }
