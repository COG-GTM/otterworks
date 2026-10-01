package com.otterworks.analytics.batch

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Path}

class EventLoaderSpec extends AnyFlatSpec with Matchers:

  private val line =
    """{"eventId":"e1","eventType":"document.created","userId":"u1","resourceId":"d1","resourceType":"document","metadata":{"k":"v"},"timestamp":"2024-03-01T10:00:00Z"}"""

  private def withTempFile(contents: String)(body: Path => Unit): Unit =
    val tmp = Files.createTempFile("event-loader-spec", ".ndjson")
    try
      Files.write(tmp, contents.getBytes(StandardCharsets.UTF_8))
      body(tmp)
    finally Files.deleteIfExists(tmp): Unit

  "EventLoader.fromString" should "parse every event field" in {
    val events = EventLoader.fromString(line)
    events should have size 1
    val e = events.head
    e.eventId shouldBe "e1"
    e.eventType shouldBe "document.created"
    e.userId shouldBe "u1"
    e.resourceId shouldBe "d1"
    e.resourceType shouldBe "document"
    e.metadata shouldBe Map("k" -> "v")
    e.timestamp.toString shouldBe "2024-03-01T10:00:00Z"
  }

  it should "return nothing for an input of only blanks and comments" in {
    EventLoader.fromString("\n   \n# only a comment\n") shouldBe empty
  }

  it should "reject a malformed line rather than silently dropping it" in {
    a[Exception] should be thrownBy EventLoader.fromString("{not json}")
  }

  "EventLoader.fromFile" should "read NDJSON from disk" in {
    withTempFile(s"# header\n$line\n\n$line\n") { path =>
      EventLoader.fromFile(path) should have size 2
    }
  }

  "EventLoader.fromResource" should "fail with a helpful message for a missing resource" in {
    val ex = the[IllegalArgumentException] thrownBy EventLoader.fromResource("/seed/does-not-exist.ndjson")
    ex.getMessage should include("/seed/does-not-exist.ndjson")
  }

  "EventLoader.load" should "read an existing filesystem path as a file" in {
    withTempFile(s"$line\n") { path =>
      val events = EventLoader.load(path.toString)
      events should have size 1
      events.head.eventId shouldBe "e1"
    }
  }

  it should "fall back to the classpath when the reference is not a file" in {
    EventLoader.load(UsageRollupJob.DefaultInput) should have size 165
  }
