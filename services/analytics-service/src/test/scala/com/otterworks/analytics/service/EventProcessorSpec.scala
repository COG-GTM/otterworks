package com.otterworks.analytics.service

import akka.actor.typed.ActorSystem
import akka.actor.typed.scaladsl.Behaviors
import com.otterworks.analytics.config.{AppConfig, PostgresConfig}
import com.otterworks.analytics.model.AnalyticsEvent
import com.otterworks.analytics.repository.MetricsRepository
import com.sun.net.httpserver.{HttpExchange, HttpServer}
import com.typesafe.config.ConfigFactory
import org.scalatest.BeforeAndAfterAll
import org.scalatest.concurrent.{Eventually, ScalaFutures}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import java.net.InetSocketAddress
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.{ConcurrentLinkedQueue, Executors}
import scala.concurrent.duration.*
import scala.concurrent.{ExecutionContext, Future}
import scala.jdk.CollectionConverters.*

/**
 * Drives [[EventProcessor]] against an in-process stub of the SQS wire protocol bound to a
 * loopback port: no AWS account, no network egress and no Docker are involved, but the
 * receive/decode/track/delete pipeline (including each of its failure arms) is really executed.
 */
class EventProcessorSpec extends AnyFlatSpec with Matchers with BeforeAndAfterAll with Eventually with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(30, Seconds), interval = Span(250, Millis))

  private given system: ActorSystem[Nothing] = ActorSystem(Behaviors.empty, "event-processor-spec")
  private given ec: ExecutionContext = system.executionContext

  private val savedAccessKey = Option(System.getProperty("aws.accessKeyId"))
  private val savedSecretKey = Option(System.getProperty("aws.secretAccessKey"))

  override def beforeAll(): Unit =
    // Pin static credentials so the SDK's default provider chain resolves deterministically
    // (the stub never verifies the signature).
    System.setProperty("aws.accessKeyId", "test-access-key")
    System.setProperty("aws.secretAccessKey", "test-secret-key")

  override def afterAll(): Unit =
    savedAccessKey.fold(System.clearProperty("aws.accessKeyId"))(System.setProperty("aws.accessKeyId", _)): Unit
    savedSecretKey.fold(System.clearProperty("aws.secretAccessKey"))(System.setProperty("aws.secretAccessKey", _)): Unit
    system.terminate()

  private val pgConfig = PostgresConfig("jdbc:postgresql://localhost:5432/test", "t", "t", 2)

  private def payload(eventType: String, userId: String, withMetadata: Boolean): String =
    val metadata = if withMetadata then ""","metadata":{"title":"Q1 plan"}""" else ""
    s"""{"eventType":"$eventType","userId":"$userId","resourceId":"doc-1","resourceType":"document"$metadata}"""

  private def md5Hex(body: String): String =
    MessageDigest.getInstance("MD5")
      .digest(body.getBytes(StandardCharsets.UTF_8))
      .map(b => f"${b & 0xff}%02x")
      .mkString

  /**
   * Minimal SQS stub. `batches` are handed out one ReceiveMessage call at a time (an empty
   * batch once they run out); `receiveFailures` initial receive calls answer HTTP 500 first,
   * and `failDeletes` makes every DeleteMessage answer HTTP 500.
   */
  private class SqsStub(
      batches: List[List[String]],
      receiveFailures: Int = 0,
      failDeletes: Boolean = false
  ):
    private val server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0)
    private val remaining = scala.collection.mutable.Queue.from(batches)
    private val receiveCalls = AtomicInteger(0)
    val deletedReceiptHandles = ConcurrentLinkedQueue[String]()

    server.setExecutor(Executors.newFixedThreadPool(2))
    server.createContext("/", (exchange: HttpExchange) => handle(exchange))
    server.start()

    val endpoint: String = s"http://127.0.0.1:${server.getAddress.getPort}"

    def deleted: List[String] = deletedReceiptHandles.asScala.toList
    def stop(): Unit = server.stop(0)

    private def handle(exchange: HttpExchange): Unit =
      val body = new String(exchange.getRequestBody.readAllBytes(), StandardCharsets.UTF_8)
      val target = Option(exchange.getRequestHeaders.getFirst("X-Amz-Target")).getOrElse("")
      val (statusCode, response) =
        if target.endsWith("ReceiveMessage") then receiveResponse()
        else if target.endsWith("DeleteMessage") then deleteResponse(body)
        else (400, """{"__type":"UnsupportedOperation"}""")
      val bytes = response.getBytes(StandardCharsets.UTF_8)
      exchange.getResponseHeaders.add("Content-Type", "application/x-amz-json-1.0")
      exchange.sendResponseHeaders(statusCode, bytes.length.toLong)
      exchange.getResponseBody.write(bytes)
      exchange.close()

    private def receiveResponse(): (Int, String) =
      if receiveCalls.getAndIncrement() < receiveFailures then
        (500, """{"__type":"InternalFailure","message":"stub failure"}""")
      else
        val batch = synchronized(if remaining.isEmpty then List.empty else remaining.dequeue())
        val messages = batch.zipWithIndex.map { case (msgBody, i) =>
          val escaped = msgBody.replace("\\", "\\\\").replace("\"", "\\\"")
          s"""{"MessageId":"m-$i","ReceiptHandle":"rh-${md5Hex(msgBody).take(8)}",""" +
            s""""MD5OfBody":"${md5Hex(msgBody)}","Body":"$escaped"}"""
        }
        (200, s"""{"Messages":[${messages.mkString(",")}]}""")

    private def deleteResponse(body: String): (Int, String) =
      val handle = """"ReceiptHandle"\s*:\s*"([^"]+)"""".r.findFirstMatchIn(body).map(_.group(1)).getOrElse("")
      deletedReceiptHandles.add(handle): Unit
      if failDeletes then (500, """{"__type":"InternalFailure","message":"delete failed"}""")
      else (200, "{}")

  private def appConfig(endpoint: String): AppConfig =
    AppConfig.fromConfig(ConfigFactory.parseString(
      s"""analytics {
         |  s3.data-lake-bucket = "bucket"
         |  sqs.events-queue-url = "$endpoint/000000000000/analytics-events"
         |  aws { region = "us-east-1", endpoint-url = "$endpoint" }
         |  postgres { url = "jdbc:postgresql://localhost:5432/test", user = "t", password = "t", max-pool-size = 2 }
         |}""".stripMargin))

  private def withStub(stub: SqsStub)(body: (AppConfig) => Unit): Unit =
    try body(appConfig(stub.endpoint))
    finally stub.stop()

  "EventProcessor" should "track a decodable SQS message and delete it from the queue" in {
    val stub = SqsStub(List(List(payload("document.created", "user-1", withMetadata = true))))
    withStub(stub) { config =>
      val repo = MetricsRepository(pgConfig)
      EventProcessor(config, AnalyticsService(repo)).start()

      eventually {
        repo.getEventCount.futureValue shouldBe 1L
      }
      val activity = repo.getUserActivity("user-1").futureValue
      activity.totalEvents shouldBe 1L
      activity.recentEvents.head.eventType shouldBe "document.created"
      eventually {
        stub.deleted should have size 1
      }
    }
  }

  it should "default absent metadata to an empty map" in {
    val stub = SqsStub(List(List(payload("file.uploaded", "user-2", withMetadata = false))))
    withStub(stub) { config =>
      val repo = MetricsRepository(pgConfig)
      EventProcessor(config, AnalyticsService(repo)).start()

      eventually {
        repo.getEventCount.futureValue shouldBe 1L
      }
      val exported = repo.getExportData("30d").futureValue
      exported.head("event_type") shouldBe "file.uploaded"
      exported.head("user_id") shouldBe "user-2"
    }
  }

  it should "drop an undecodable message from the queue without tracking it" in {
    val stub = SqsStub(List(List("not-json-at-all")))
    withStub(stub) { config =>
      val repo = MetricsRepository(pgConfig)
      EventProcessor(config, AnalyticsService(repo)).start()

      eventually {
        stub.deleted should have size 1
      }
      repo.getEventCount.futureValue shouldBe 0L
    }
  }

  it should "keep polling after a failed ReceiveMessage call" in {
    val stub = SqsStub(
      List(List(payload("document.viewed", "user-3", withMetadata = false))),
      receiveFailures = 1
    )
    withStub(stub) { config =>
      val repo = MetricsRepository(pgConfig)
      EventProcessor(config, AnalyticsService(repo)).start()

      eventually {
        repo.getEventCount.futureValue shouldBe 1L
      }
    }
  }

  it should "still track the event when the delete call fails" in {
    val stub = SqsStub(
      List(List(payload("document.edited", "user-4", withMetadata = true), "}{ broken")),
      failDeletes = true
    )
    withStub(stub) { config =>
      val repo = MetricsRepository(pgConfig)
      EventProcessor(config, AnalyticsService(repo)).start()

      eventually {
        repo.getEventCount.futureValue shouldBe 1L
        stub.deleted.size should be >= 2
      }
    }
  }

  it should "survive a repository failure and go on processing later messages" in {
    val stub = SqsStub(List(
      List(payload("document.created", "user-5", withMetadata = false)),
      List(payload("document.created", "user-6", withMetadata = false))
    ))
    withStub(stub) { config =>
      val delegate = MetricsRepository(pgConfig)
      val failFirst = AtomicInteger(0)
      val flaky = new MetricsRepository:
        export delegate.{storeEvent as _, *}
        def storeEvent(event: AnalyticsEvent): Future[Unit] =
          if failFirst.getAndIncrement() == 0 then Future.failed(RuntimeException("store failed"))
          else delegate.storeEvent(event)

      EventProcessor(config, AnalyticsService(flaky)).start()

      // The first message is lost (never deleted, never stored) but the stream stays alive
      // and the message delivered on the next poll is processed normally.
      eventually {
        delegate.getEventCount.futureValue shouldBe 1L
      }
      delegate.getUserActivity("user-6").futureValue.totalEvents shouldBe 1L
      delegate.getUserActivity("user-5").futureValue.totalEvents shouldBe 0L
      stub.deleted should have size 1
    }
  }
