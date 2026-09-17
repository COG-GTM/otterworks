package com.otterworks.analytics.model

import com.otterworks.analytics.model.AnalyticsEventJsonProtocol.given
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

import java.time.Instant

/** Timestamps arrive either as ISO-8601 strings (REST/NDJSON) or epoch millis (legacy producers). */
class InstantFormatSpec extends AnyFlatSpec with Matchers:

  private val format = summon[JsonFormat[Instant]]

  "instantFormat" should "write an ISO-8601 string" in {
    format.write(Instant.parse("2024-03-01T12:30:00Z")) shouldBe JsString("2024-03-01T12:30:00Z")
  }

  it should "read an ISO-8601 string" in {
    format.read(JsString("2024-03-01T12:30:00Z")) shouldBe Instant.parse("2024-03-01T12:30:00Z")
  }

  it should "read epoch millis" in {
    format.read(JsNumber(1709296200000L)) shouldBe Instant.ofEpochMilli(1709296200000L)
  }

  it should "reject any other JSON shape" in {
    val ex = intercept[DeserializationException](format.read(JsBoolean(true)))

    ex.getMessage should include("Expected ISO-8601 string or epoch millis")
  }
