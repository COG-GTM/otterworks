package com.otterworks.analytics.model

import com.otterworks.analytics.model.AnalyticsEventJsonProtocol.{*, given}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

import java.time.Instant

/** Wire-contract coverage for the event JSON protocol, including both Instant encodings. */
class AnalyticsEventJsonProtocolSpec extends AnyFlatSpec with Matchers:

  private val event = AnalyticsEvent(
    eventId = "e-1",
    eventType = EventType.DocumentCreated,
    userId = "u-1",
    resourceId = "d-1",
    resourceType = "document",
    metadata = Map("title" -> "Quarterly report"),
    timestamp = Instant.parse("2024-03-01T10:15:30Z")
  )

  "The analytics event format" should "round-trip an event through JSON" in {
    val json = event.toJson
    json.asJsObject.fields("timestamp") shouldBe JsString("2024-03-01T10:15:30Z")
    json.convertTo[AnalyticsEvent] shouldBe event
  }

  "The Instant format" should "read an ISO-8601 string" in {
    JsString("2024-03-01T10:15:30Z").convertTo[Instant] shouldBe Instant.parse("2024-03-01T10:15:30Z")
  }

  it should "read epoch millis as an instant" in {
    JsNumber(1709287530000L).convertTo[Instant] shouldBe Instant.parse("2024-03-01T10:05:30Z")
  }

  it should "reject any other JSON shape" in {
    val ex = the[DeserializationException] thrownBy JsBoolean(true).convertTo[Instant]
    ex.getMessage should include("Expected ISO-8601 string or epoch millis")
  }

  "TrackEventRequest" should "treat metadata as optional on the wire" in {
    val parsed = """{"eventType":"file.uploaded","userId":"u-2","resourceId":"f-1","resourceType":"file"}"""
      .parseJson.convertTo[TrackEventRequest]
    parsed.metadata shouldBe None
    parsed.eventType shouldBe EventType.FileUploaded
  }

  "AcceptedResponse" should "serialize as a status/eventId pair" in {
    AcceptedResponse("accepted", "e-1").toJson.asJsObject.fields shouldBe
      Map("status" -> JsString("accepted"), "eventId" -> JsString("e-1"))
  }

  "AnalyticsEvent.create" should "default the metadata to empty and stamp identity and time" in {
    val created = AnalyticsEvent.create("document.viewed", "u-3", "d-9", "document")
    created.metadata shouldBe empty
    created.eventId should fullyMatch regex "[0-9a-f-]{36}"
    created.timestamp.isAfter(Instant.parse("2024-01-01T00:00:00Z")) shouldBe true
  }

  "EventType.All" should "contain every declared event type exactly once" in {
    EventType.All should have size 15
    EventType.All should contain allOf (EventType.DocumentCreated, EventType.StorageReleased)
  }
