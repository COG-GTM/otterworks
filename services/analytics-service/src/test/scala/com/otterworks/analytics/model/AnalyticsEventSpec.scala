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
    request.userId shouldBe Some("user-1")
    request.resourceId shouldBe "doc-1"
    request.resourceType shouldBe "document"
    request.metadata shouldBe Some(Map("title" -> "Test"))
  }

  it should "handle missing optional metadata" in {
    val jsonStr = """{"eventType":"file.uploaded","userId":"user-2","resourceId":"file-1","resourceType":"file"}"""
    val request = jsonStr.parseJson.convertTo[TrackEventRequest]

    request.metadata shouldBe None
  }

  it should "treat userId as optional" in {
    val jsonStr = """{"eventType":"document.viewed","resourceId":"doc-1","resourceType":"document"}"""
    val request = jsonStr.parseJson.convertTo[TrackEventRequest]

    request.userId shouldBe None
  }

  "TrackEventPolicy" should "accept a well-formed client event" in {
    val request = TrackEventRequest("document.viewed", None, "doc-1", "document", Some(Map("source" -> "web")))
    TrackEventPolicy.validate(request) shouldBe Right(())
  }

  it should "reject event types outside EventType.All" in {
    val request = TrackEventRequest("document_viewed", None, "doc-1", "document", None)
    TrackEventPolicy.validate(request).isLeft shouldBe true
  }

  it should "reject storage accounting events from the REST ingest" in {
    Seq(EventType.StorageAllocated, EventType.StorageReleased).foreach { eventType =>
      val request = TrackEventRequest(eventType, None, "file-1", "file", Some(Map("bytes" -> "999999999")))
      TrackEventPolicy.validate(request).isLeft shouldBe true
    }
  }

  it should "reject identifiers that could become CSV formulas" in {
    TrackEventPolicy.validate(TrackEventRequest("document.viewed", None, "=HYPERLINK(1)", "document", None)).isLeft shouldBe true
    TrackEventPolicy.validate(TrackEventRequest("document.viewed", None, "doc-1", "+cmd", None)).isLeft shouldBe true
  }

  it should "bound metadata size and content" in {
    val tooMany = (1 to TrackEventPolicy.MaxMetadataEntries + 1).map(i => s"k$i" -> "v").toMap
    val tooLong = Map("k" -> "x" * (TrackEventPolicy.MaxMetadataValueLength + 1))
    val badKey = Map("bad key" -> "v")
    val control = Map("k" -> "line1\nline2")
    Seq(tooMany, tooLong, badKey, control).foreach { metadata =>
      TrackEventPolicy.validate(TrackEventRequest("document.viewed", None, "doc-1", "document", Some(metadata))).isLeft shouldBe true
    }
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
