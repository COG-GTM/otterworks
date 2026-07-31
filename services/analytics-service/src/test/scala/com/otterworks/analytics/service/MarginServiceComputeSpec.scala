package com.otterworks.analytics.service

import com.otterworks.analytics.model.Product
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

/** Boundary cases of the locked margin formula (OTD-15). */
class MarginServiceComputeSpec extends AnyFlatSpec with Matchers:

  private def product(listPriceUsd: BigDecimal, currency: String = "USD"): Product = Product(
    sku = "SKU-1",
    name = "Sample",
    category = "Grocery",
    commoditySeriesCode = if currency == "NOK" then "SALMON_NOK_KG" else "SUGAR_USD_KG",
    contentKg = BigDecimal("2.0"),
    freightKg = BigDecimal("1.0"),
    overheadPct = BigDecimal("10.00"),
    listPriceUsd = listPriceUsd,
    supplier = "Acme"
  )

  "computeMargin" should "report a zero margin rather than dividing by a zero list price" in {
    val m = MarginService.computeMargin(
      product(BigDecimal(0)),
      commodityPrice = BigDecimal(5),
      commodityCurrency = "USD",
      usdNok = BigDecimal(10),
      wciUsdFeu = BigDecimal(2500)
    )
    m.marginPct shouldBe BigDecimal(0)
    m.commodityCostUsd shouldBe BigDecimal("10.0000")
    m.cogsUsd shouldBe BigDecimal("11.1100")
  }

  it should "report a negative margin when the cost exceeds the list price" in {
    val m = MarginService.computeMargin(
      product(BigDecimal("5.00")),
      commodityPrice = BigDecimal(5),
      commodityCurrency = "USD",
      usdNok = BigDecimal(10),
      wciUsdFeu = BigDecimal(2500)
    )
    m.cogsUsd shouldBe BigDecimal("11.1100")
    m.marginPct shouldBe BigDecimal("-122.2000")
  }

  it should "leave the margin date to the caller" in {
    MarginService.computeMargin(
      product(BigDecimal("30.00")),
      BigDecimal(5),
      "USD",
      BigDecimal(10),
      BigDecimal(2500)
    ).marginDate shouldBe ""
  }

  "The locked series codes" should "match the shared market-series catalog" in {
    MarginService.FxSeriesCode shouldBe "USD_NOK"
    MarginService.FreightSeriesCode shouldBe "DREWRY_WCI_USD_FEU"
    MarginService.SalmonSeriesCode shouldBe "SALMON_NOK_KG"
    MarginService.KgPerFeu shouldBe BigDecimal(25000)
  }
