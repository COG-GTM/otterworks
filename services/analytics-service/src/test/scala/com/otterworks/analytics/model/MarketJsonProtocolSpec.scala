package com.otterworks.analytics.model

import com.otterworks.analytics.model.MarketJsonProtocol.{*, given}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

/** The market/margin payloads are snake_case on the wire; the web client depends on it. */
class MarketJsonProtocolSpec extends AnyFlatSpec with Matchers:

  private val product = Product(
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

  "The product format" should "emit snake_case keys and round-trip" in {
    val fields = product.toJson.asJsObject.fields
    fields.keySet shouldBe Set(
      "sku", "name", "category", "commodity_series_code", "content_kg",
      "freight_kg", "overhead_pct", "list_price_usd", "supplier"
    )
    fields("commodity_series_code") shouldBe JsString("SALMON_NOK_KG")
    product.toJson.convertTo[Product] shouldBe product
  }

  "The series and price formats" should "round-trip through snake_case JSON" in {
    val series = MarketSeries("USD_NOK", "USD/NOK", "NOK per USD", "NOK", "fx")
    series.toJson.asJsObject.fields("series_code") shouldBe JsString("USD_NOK")
    series.toJson.convertTo[MarketSeries] shouldBe series

    val point = PricePoint("USD_NOK", "2024-03-01", BigDecimal("10.5"), "manual_pull")
    point.toJson.asJsObject.fields("price_date") shouldBe JsString("2024-03-01")
    point.toJson.convertTo[PricePoint] shouldBe point
  }

  "An observations request" should "parse the snake_case ingest payload" in {
    val request =
      """{"observations":[{"series_code":"USD_NOK","price_date":"2024-03-01","value":10.5}],
        | "source_note":"manual pull"}""".stripMargin.parseJson.convertTo[ObservationsRequest]
    request.sourceNote shouldBe Some("manual pull")
    request.observations shouldBe List(Observation("USD_NOK", "2024-03-01", BigDecimal("10.5")))
  }
