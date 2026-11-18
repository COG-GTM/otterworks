package com.otterworks.analytics.model

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*
import com.otterworks.analytics.model.AnalyticsEventJsonProtocol.{*, given}

import java.time.Instant

class AnalyticsEventSpec extends AnyFlatSpec with Matchers:

  "AnalyticsEvent.create" should "generate a unique event ID and current timestamp" in {
    val event = AnalyticsEvent.create(
      eventType = EventType.DocumentCreated,
      userId = "user-1",
      resourceId = "doc-1",
      resourceType = "document"
    )

    event.eventId should not be empty
    event.eventType shouldBe EventType.DocumentCreated
    event.userId shouldBe "user-1"
    event.resourceId shouldBe "doc-1"
    event.resourceType shouldBe "document"
    event.metadata shouldBe empty
    event.timestamp should not be null
  }

  it should "include metadata when provided" in {
    val meta = Map("title" -> "My Doc", "size" -> "1024")
    val event = AnalyticsEvent.create(
      eventType = EventType.FileUploaded,
      userId = "user-2",
      resourceId = "file-1",
      resourceType = "file",
      metadata = meta
    )

    event.metadata shouldBe meta
  }

  "AnalyticsEvent JSON serialization" should "round-trip correctly" in {
    val event = AnalyticsEvent(
      eventId = "evt-123",
      eventType = EventType.DocumentViewed,
      userId = "user-1",
      resourceId = "doc-1",
      resourceType = "document",
      metadata = Map("source" -> "web"),
      timestamp = Instant.parse("2024-01-15T10:30:00Z")
    )

    val json = event.toJson
    val parsed = json.convertTo[AnalyticsEvent]

    parsed shouldBe event
  }

  "TrackEventRequest JSON" should "deserialize correctly" in {
    val jsonStr = """{"eventType":"document.created","userId":"user-1","resourceId":"doc-1","resourceType":"document","metadata":{"title":"Test"}}"""
    val request = jsonStr.parseJson.convertTo[TrackEventRequest]

    request.eventType shouldBe "document.created"
    request.userId shouldBe "user-1"
    request.resourceId shouldBe "doc-1"
    request.resourceType shouldBe "document"
    request.metadata shouldBe Some(Map("title" -> "Test"))
  }

  it should "handle missing optional metadata" in {
    val jsonStr = """{"eventType":"file.uploaded","userId":"user-2","resourceId":"file-1","resourceType":"file"}"""
    val request = jsonStr.parseJson.convertTo[TrackEventRequest]

    request.metadata shouldBe None
  }

  "EventType" should "contain all expected event types" in {
    EventType.All should contain(EventType.DocumentCreated)
    EventType.All should contain(EventType.FileUploaded)
    EventType.All should contain(EventType.UserLoggedIn)
    EventType.All should contain(EventType.CollabSessionStarted)
    EventType.All should contain(EventType.StorageAllocated)
    EventType.All.size shouldBe 15
  }

  "Instant JSON format" should "parse ISO-8601 strings" in {
    val json = JsString("2024-03-15T12:00:00Z")
    val instant = json.convertTo[Instant]
    instant shouldBe Instant.parse("2024-03-15T12:00:00Z")
  }

  it should "parse epoch milliseconds" in {
    val json = JsNumber(1710504000000L)
    val instant = json.convertTo[Instant]
    instant shouldBe Instant.ofEpochMilli(1710504000000L)
  }

  it should "reject values that are neither strings nor numbers" in {
    a[DeserializationException] should be thrownBy JsBoolean(true).convertTo[Instant]
  }

  "Product JSON" should "round-trip with snake_case field names" in {
    import com.otterworks.analytics.model.MarketJsonProtocol.given
    val p = Product("SKU-1", "Name", "Cat", "SALMON_NOK_KG", BigDecimal("1.5"), BigDecimal("2"),
      BigDecimal("10"), BigDecimal("30"), "Supplier")
    val json = p.toJson.asJsObject
    json.fields.keySet should contain allOf("commodity_series_code", "content_kg", "list_price_usd")
    json.convertTo[Product] shouldBe p
  }
