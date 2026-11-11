package com.otterworks.analytics.api

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

class CsvSpec extends AnyFlatSpec with Matchers:

  "Csv.textField" should "leave plain values untouched" in {
    Csv.textField("document.created") shouldBe "document.created"
    Csv.textField("") shouldBe ""
  }

  it should "quote values containing separators, quotes or newlines" in {
    Csv.textField("a,b") shouldBe "\"a,b\""
    Csv.textField("say \"hi\"") shouldBe "\"say \"\"hi\"\"\""
    Csv.textField("line1\nline2") shouldBe "\"line1\nline2\""
  }

  it should "neutralize leading formula characters" in {
    Csv.textField("=1+1") shouldBe "'=1+1"
    Csv.textField("+SUM(A1)") shouldBe "'+SUM(A1)"
    Csv.textField("-2+3") shouldBe "'-2+3"
    Csv.textField("@SUM(A1)") shouldBe "'@SUM(A1)"
    Csv.textField("\t=1") shouldBe "'\t=1"
    Csv.textField("\r=1") shouldBe "\"'\r=1\""
  }

  it should "neutralize and quote a DDE payload" in {
    Csv.textField("=cmd|' /C calc'!A0,x") shouldBe "\"'=cmd|' /C calc'!A0,x\""
    Csv.textField("=HYPERLINK(\"http://evil\")") shouldBe "\"'=HYPERLINK(\"\"http://evil\"\")\""
  }
