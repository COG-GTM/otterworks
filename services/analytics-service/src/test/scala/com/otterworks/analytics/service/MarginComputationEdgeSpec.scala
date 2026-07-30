package com.otterworks.analytics.service

import com.otterworks.analytics.model.Product
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

/** Edge cases of the locked margin formula that the happy-path spec does not reach. */
class MarginComputationEdgeSpec extends AnyFlatSpec with Matchers:

  private val product = Product(
    sku = "SLM-002",
    name = "Sample Pack",
    category = "Seafood",
    commoditySeriesCode = "SALMON_NOK_KG",
    contentKg = BigDecimal("1.0"),
    freightKg = BigDecimal("1.2"),
    overheadPct = BigDecimal("15.00"),
    listPriceUsd = BigDecimal("0.00"),
    supplier = "NordicCatch AS"
  )

  "computeMargin" should "report a zero margin for a giveaway (zero list price) instead of dividing by zero" in {
    val m = MarginService.computeMargin(
      product,
      commodityPrice = BigDecimal(100),
      commodityCurrency = "NOK",
      usdNok = BigDecimal(10),
      wciUsdFeu = BigDecimal(2500)
    )

    m.marginPct shouldBe BigDecimal(0)
    m.cogsUsd shouldBe BigDecimal("11.6380")
  }

  it should "produce a negative margin when cogs exceed the list price" in {
    val m = MarginService.computeMargin(
      product.copy(listPriceUsd = BigDecimal("10.00")),
      commodityPrice = BigDecimal(100),
      commodityCurrency = "NOK",
      usdNok = BigDecimal(10),
      wciUsdFeu = BigDecimal(2500)
    )

    m.marginPct should be < BigDecimal(0)
    m.marginPct shouldBe BigDecimal("-16.3800")
  }
