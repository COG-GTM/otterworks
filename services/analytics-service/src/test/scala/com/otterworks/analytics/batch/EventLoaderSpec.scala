package com.otterworks.analytics.batch

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.nio.charset.StandardCharsets
import java.nio.file.Files

/** Covers every input shape the bulk NDJSON loader accepts, plus its failure mode. */
class EventLoaderSpec extends AnyFlatSpec with Matchers:

  private val ndjson =
    """# a comment line, ignored
      |
      |{"eventId":"e-1","eventType":"document.created","metadata":{"title":"A"},"resourceId":"doc-1","resourceType":"document","timestamp":"2024-03-01T00:00:00Z","userId":"user-01"}
      |{"eventId":"e-2","eventType":"file.uploaded","metadata":{},"resourceId":"file-1","resourceType":"file","timestamp":"2024-03-02T10:15:00Z","userId":"user-02"}
      |""".stripMargin

  private def withTempFile[A](contents: String)(f: java.nio.file.Path => A): A =
    val path = Files.createTempFile("events", ".ndjson")
    try
      Files.write(path, contents.getBytes(StandardCharsets.UTF_8))
      f(path)
    finally Files.deleteIfExists(path): Unit

  "EventLoader.fromString" should "parse events and skip blank and commented lines" in {
    val events = EventLoader.fromString(ndjson)

    events should have size 2
    events.map(_.eventId) shouldBe List("e-1", "e-2")
    events.head.metadata shouldBe Map("title" -> "A")
    events(1).eventType shouldBe "file.uploaded"
    events(1).timestamp.toString shouldBe "2024-03-02T10:15:00Z"
  }

  "EventLoader.fromFile" should "read events from a file on disk" in {
    withTempFile(ndjson) { path =>
      EventLoader.fromFile(path).map(_.eventId) shouldBe List("e-1", "e-2")
    }
  }

  "EventLoader.load" should "read an existing filesystem path as a file" in {
    withTempFile(ndjson) { path =>
      EventLoader.load(path.toString) shouldBe EventLoader.fromString(ndjson)
    }
  }

  it should "fall back to the classpath when the reference is not a file" in {
    val events = EventLoader.load(UsageRollupJob.DefaultInput)

    events.size should be > 100
    all(events.map(_.eventId)) should not be empty
  }

  "EventLoader.fromResource" should "fail with a helpful message for a missing resource" in {
    val ex = intercept[IllegalArgumentException](EventLoader.fromResource("/seed/does-not-exist.ndjson"))

    ex.getMessage should include("/seed/does-not-exist.ndjson")
  }
