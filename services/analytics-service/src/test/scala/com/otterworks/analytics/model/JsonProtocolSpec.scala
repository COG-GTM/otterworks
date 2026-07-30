package com.otterworks.analytics.model

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

import java.time.Instant

/** Wire formats that are not exercised through the HTTP routes. */
class JsonProtocolSpec extends AnyFlatSpec with Matchers:

  "the Instant format" should "accept ISO-8601 strings and epoch millis" in {
    import AnalyticsEventJsonProtocol.given
    val format = summon[JsonFormat[Instant]]

    format.read(JsString("2024-03-01T10:15:30Z")) shouldBe Instant.parse("2024-03-01T10:15:30Z")
    format.read(JsNumber(1709287200000L)) shouldBe Instant.ofEpochMilli(1709287200000L)
    format.write(Instant.parse("2024-03-01T10:15:30Z")) shouldBe JsString("2024-03-01T10:15:30Z")
  }

  it should "reject a timestamp that is neither a string nor a number" in {
    import AnalyticsEventJsonProtocol.given
    val format = summon[JsonFormat[Instant]]

    val failure = the[DeserializationException] thrownBy format.read(JsBoolean(true))
    failure.getMessage should include("Expected ISO-8601 string or epoch millis")
  }

  "the market formats" should "round-trip a product over its snake_case wire shape" in {
    import MarketJsonProtocol.given
    val product = Product(
      sku = "SLM-001",
      name = "Atlantic Salmon Fillet",
      category = "Seafood",
      commoditySeriesCode = "SALMON_NOK_KG",
      contentKg = BigDecimal("1.0"),
      freightKg = BigDecimal("1.2"),
      overheadPct = BigDecimal("15.00"),
      listPriceUsd = BigDecimal("30.00"),
      supplier = "NordicCatch AS"
    )

    val json = product.toJson.asJsObject
    json.fields.keySet shouldBe Set(
      "sku", "name", "category", "commodity_series_code", "content_kg",
      "freight_kg", "overhead_pct", "list_price_usd", "supplier"
    )
    json.convertTo[Product] shouldBe product
  }

  it should "round-trip the daily rollup report" in {
    import UsageRollupJsonProtocol.given
    val report = UsageRollupReport(
      generatedAt = "2024-03-04T02:00:00Z",
      source = "/seed/usage-events.ndjson",
      windowStart = Some("2024-03-01"),
      windowEnd = Some("2024-03-01"),
      dayCount = 1L,
      totalEvents = 2L,
      rollups = List(
        DailyUsageRollup("2024-03-01", 2L, 1L, 1L, 1L, 0L, 0L, 0L, 0L, 0L, 0L, 0L)
      )
    )

    report.toJson.convertTo[UsageRollupReport] shouldBe report
  }
