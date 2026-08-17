package com.otterworks.analytics.model

import com.otterworks.analytics.model.AnalyticsEventJsonProtocol.{*, given}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

import java.time.Instant

class AnalyticsEventJsonSpec extends AnyFlatSpec with Matchers:

  "the Instant format" should "round-trip an ISO-8601 string" in {
    val instant = Instant.parse("2024-03-01T10:15:30Z")
    instant.toJson shouldBe JsString("2024-03-01T10:15:30Z")
    instant.toJson.convertTo[Instant] shouldBe instant
  }

  it should "accept epoch millis" in {
    JsNumber(1709287200000L).convertTo[Instant] shouldBe Instant.ofEpochMilli(1709287200000L)
  }

  it should "reject a value that is neither a string nor a number" in {
    val ex = the[DeserializationException] thrownBy JsBoolean(true).convertTo[Instant]
    ex.getMessage should include("Expected ISO-8601 string or epoch millis")
  }

  "the AnalyticsEvent format" should "round-trip every field" in {
    val event = AnalyticsEvent.create("document.created", "u1", "d1", "document", Map("title" -> "T"))
    event.toJson.convertTo[AnalyticsEvent] shouldBe event
  }
