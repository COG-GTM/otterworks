package com.otterworks.analytics.model

import com.otterworks.analytics.model.MarketJsonProtocol.{*, given}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

/** The market wire format is snake_case; these formats are the contract with the web client. */
class MarketJsonProtocolSpec extends AnyFlatSpec with Matchers:

  "PricePoint" should "serialize to the snake_case wire format" in {
    val point = PricePoint("SALMON_NOK_KG", "2026-07-01", BigDecimal("102.5000"), "seed")

    val fields = point.toJson.asJsObject.fields

    fields.keySet shouldBe Set("series_code", "price_date", "value", "source")
    fields("series_code") shouldBe JsString("SALMON_NOK_KG")
    fields("price_date") shouldBe JsString("2026-07-01")
    fields("value") shouldBe JsNumber(BigDecimal("102.5000"))
    fields("source") shouldBe JsString("seed")
  }

  it should "round-trip through the wire format" in {
    val point = PricePoint("USD_NOK", "2026-07-02", BigDecimal("10.4321"), "manual")

    point.toJson.convertTo[PricePoint] shouldBe point
  }

  "MarketSeries" should "round-trip through the wire format" in {
    val series = MarketSeries("DREWRY_WCI_USD_FEU", "Drewry WCI", "USD/FEU", "USD", "freight")

    series.toJson.asJsObject.fields.keySet shouldBe Set("series_code", "name", "unit", "currency", "category")
    series.toJson.convertTo[MarketSeries] shouldBe series
  }

  "Product" should "round-trip through the snake_case wire format" in {
    val product = Product(
      sku = "SLM-001",
      name = "Atlantic Salmon Fillet",
      category = "Seafood",
      commoditySeriesCode = "SALMON_NOK_KG",
      contentKg = BigDecimal("1.3623"),
      freightKg = BigDecimal("1.5033"),
      overheadPct = BigDecimal("13.11"),
      listPriceUsd = BigDecimal("32.65"),
      supplier = "NordicCatch AS"
    )

    product.toJson.asJsObject.fields.keySet shouldBe Set(
      "sku", "name", "category", "commodity_series_code", "content_kg",
      "freight_kg", "overhead_pct", "list_price_usd", "supplier"
    )
    product.toJson.convertTo[Product] shouldBe product
  }
