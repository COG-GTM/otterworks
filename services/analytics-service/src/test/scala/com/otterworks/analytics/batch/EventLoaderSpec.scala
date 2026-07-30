package com.otterworks.analytics.batch

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.nio.charset.StandardCharsets
import java.nio.file.Files

/** The bulk NDJSON input of the nightly batch job: files, classpath resources and resolution. */
class EventLoaderSpec extends AnyFlatSpec with Matchers:

  private val ndjson =
    """# seeded events
      |
      |{"eventId":"e1","eventType":"document.created","userId":"u1","resourceId":"d1","resourceType":"document","metadata":{"title":"Alpha"},"timestamp":"2024-03-01T00:00:00Z"}
      |{"eventId":"e2","eventType":"file.uploaded","userId":"u2","resourceId":"f1","resourceType":"file","metadata":{},"timestamp":"2024-03-01T01:00:00Z"}
      |""".stripMargin

  private def withTempFile[A](contents: String)(body: java.nio.file.Path => A): A =
    val path = Files.createTempFile("event-loader-spec", ".ndjson")
    try
      Files.write(path, contents.getBytes(StandardCharsets.UTF_8))
      body(path)
    finally Files.deleteIfExists(path): Unit

  "EventLoader.fromFile" should "read events from disk, skipping comments and blank lines" in {
    withTempFile(ndjson) { path =>
      val events = EventLoader.fromFile(path)
      events.map(_.eventId) shouldBe List("e1", "e2")
      events.head.metadata shouldBe Map("title" -> "Alpha")
    }
  }

  "EventLoader.load" should "read an existing filesystem path as a file" in {
    withTempFile(ndjson) { path =>
      EventLoader.load(path.toString).map(_.eventId) shouldBe List("e1", "e2")
    }
  }

  it should "fall back to the classpath for a non-file reference" in {
    EventLoader.load(UsageRollupJob.DefaultInput) should have size 165
  }

  "EventLoader.fromResource" should "fail loudly when the resource is missing" in {
    val failure = the[IllegalArgumentException] thrownBy EventLoader.fromResource("/seed/does-not-exist.ndjson")
    failure.getMessage should include("Seed resource not found on classpath")
  }
