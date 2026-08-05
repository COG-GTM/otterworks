package com.otterworks.analytics.batch

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Path}

/** Covers the three input flavours of the bulk NDJSON loader: string, file and classpath. */
class EventLoaderSpec extends AnyFlatSpec with Matchers:

  private val ndjson =
    """# seed comment
      |{"eventId":"e1","eventType":"document.created","userId":"u1","resourceId":"d1","resourceType":"document","metadata":{"title":"A"},"timestamp":"2024-03-01T10:00:00Z"}
      |
      |{"eventId":"e2","eventType":"file.uploaded","userId":"u2","resourceId":"f1","resourceType":"file","metadata":{},"timestamp":"2024-03-01T11:00:00Z"}
      |""".stripMargin

  private def withTempFile[A](content: String)(f: Path => A): A =
    val tmp = Files.createTempFile("event-loader-spec", ".ndjson")
    try
      Files.write(tmp, content.getBytes(StandardCharsets.UTF_8))
      f(tmp)
    finally Files.deleteIfExists(tmp): Unit

  "EventLoader.fromFile" should "parse every event in an NDJSON file" in {
    withTempFile(ndjson) { path =>
      val events = EventLoader.fromFile(path)
      events.map(_.eventId) shouldBe List("e1", "e2")
      events.head.metadata shouldBe Map("title" -> "A")
      events.head.timestamp.toString shouldBe "2024-03-01T10:00:00Z"
    }
  }

  "EventLoader.load" should "read an existing filesystem path as a file" in {
    withTempFile(ndjson) { path =>
      EventLoader.load(path.toString).map(_.eventType) shouldBe
        List("document.created", "file.uploaded")
    }
  }

  it should "fall back to the classpath when the reference is not a file on disk" in {
    EventLoader.load(UsageRollupJob.DefaultInput) shouldBe
      EventLoader.fromResource(UsageRollupJob.DefaultInput)
  }

  "EventLoader.fromResource" should "fail with a helpful message for an unknown resource" in {
    val ex = the[IllegalArgumentException] thrownBy EventLoader.fromResource("/seed/does-not-exist.ndjson")
    ex.getMessage should include("/seed/does-not-exist.ndjson")
  }

  "EventLoader.fromString" should "reject a malformed line rather than skipping it" in {
    a[Exception] should be thrownBy EventLoader.fromString("{not-json}")
  }
