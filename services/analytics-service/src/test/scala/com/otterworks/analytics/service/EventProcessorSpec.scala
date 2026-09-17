package com.otterworks.analytics.service

import akka.actor.typed.ActorSystem
import akka.actor.typed.scaladsl.Behaviors
import com.otterworks.analytics.config.*
import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.{InMemoryMetricsRepository, MetricsRepository}
import org.scalatest.BeforeAndAfterAll
import org.scalatest.concurrent.{Eventually, ScalaFutures}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import software.amazon.awssdk.services.sqs.SqsClient
import software.amazon.awssdk.services.sqs.model.{
  DeleteMessageRequest,
  DeleteMessageResponse,
  Message,
  ReceiveMessageRequest,
  ReceiveMessageResponse
}

import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicInteger
import scala.concurrent.{ExecutionContext, Future}
import scala.jdk.CollectionConverters.*

/**
 * Drives the SQS consumer end-to-end against an in-process stub of the AWS client:
 * decoding, tracking, deletion, and each of the three failure paths (receive, decode,
 * track). No AWS call and no network I/O is made.
 */
class EventProcessorSpec
    extends AnyFlatSpec
    with Matchers
    with Eventually
    with ScalaFutures
    with BeforeAndAfterAll:

  private given system: ActorSystem[Nothing] = ActorSystem(Behaviors.empty, "event-processor-spec")
  private given ec: ExecutionContext = system.executionContext

  // The consumer's first poll happens one second after start(), then every five.
  given PatienceConfig = PatienceConfig(timeout = Span(20, Seconds), interval = Span(100, Millis))

  override def afterAll(): Unit =
    system.terminate()
    super.afterAll()

  private val postgres = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)

  private def appConfig(endpoint: Option[String] = None): AppConfig = AppConfig(
    s3 = S3Config("lake"),
    sqs = SqsConfig("http://sqs.local/queue"),
    aws = AwsConfig("us-east-1", endpoint),
    postgres = postgres,
    repository = RepositoryConfig("in-memory"),
    server = ServerConfig("0.0.0.0", 8088)
  )

  private def payload(eventType: String, userId: String = "u1"): String =
    s"""{"eventType":"$eventType","userId":"$userId","resourceId":"doc-1","resourceType":"document"}"""

  private def message(body: String, handle: String): Message =
    Message.builder().body(body).receiptHandle(handle).messageId(handle).build()

  /** In-process stand-in for the AWS SQS client: one scripted batch per poll. */
  private class StubSqsClient(
      batches: List[List[Message]],
      failReceiveTimes: Int = 0,
      failDelete: Boolean = false
  ) extends SqsClient:
    val receiveCalls = new AtomicInteger(0)
    val deletedHandles = new ConcurrentLinkedQueue[String]()

    override def serviceName(): String = "sqs-stub"
    override def close(): Unit = ()

    override def receiveMessage(request: ReceiveMessageRequest): ReceiveMessageResponse =
      val call = receiveCalls.getAndIncrement()
      if call < failReceiveTimes then throw new RuntimeException("SQS unreachable")
      val batch = batches.lift(call - failReceiveTimes).getOrElse(Nil)
      ReceiveMessageResponse.builder().messages(batch.asJava).build()

    override def deleteMessage(request: DeleteMessageRequest): DeleteMessageResponse =
      if failDelete then throw new RuntimeException("delete rejected")
      deletedHandles.add(request.receiptHandle())
      DeleteMessageResponse.builder().build()

  /** Injects the stub in place of the lazily built AWS client. */
  private class StubbedProcessor(config: AppConfig, service: AnalyticsService, stub: SqsClient)
      extends EventProcessor(config, service):
    override protected lazy val sqsClient: SqsClient = stub

  /** Exposes the real, lazily built AWS client for construction-only assertions. */
  private class InspectableProcessor(config: AppConfig, service: AnalyticsService)
      extends EventProcessor(config, service):
    def client: SqsClient = sqsClient

  private class FailingStoreRepository extends MetricsRepository:
    private val delegate = new InMemoryMetricsRepository(postgres)
    export delegate.{storeEvent as _, *}
    def storeEvent(event: AnalyticsEvent): Future[Unit] = Future.failed(RuntimeException("store failed"))

  "EventProcessor.start" should "track every decodable message and delete it from the queue" in {
    val repo = MetricsRepository(postgres)
    val service = AnalyticsService(repo)
    val stub = new StubSqsClient(List(List(
      message(payload("document.created"), "h1"),
      message(payload("file.uploaded", "u2"), "h2")
    )))
    new StubbedProcessor(appConfig(), service, stub).start()

    eventually {
      stub.deletedHandles.asScala.toSet shouldBe Set("h1", "h2")
    }
    eventually {
      repo.getEventCount.futureValue shouldBe 2L
    }
    repo.getDashboardSummary("7d").futureValue.totalEvents shouldBe 2L
  }

  it should "keep polling after a transient receive failure" in {
    val repo = MetricsRepository(postgres)
    val stub = new StubSqsClient(
      List(List(message(payload("document.viewed"), "retry-1"))),
      failReceiveTimes = 1
    )
    new StubbedProcessor(appConfig(), AnalyticsService(repo), stub).start()

    eventually {
      stub.receiveCalls.get() should be >= 2
      stub.deletedHandles.asScala.toList shouldBe List("retry-1")
    }
  }

  it should "drop an undecodable message from the queue without tracking an event" in {
    val repo = MetricsRepository(postgres)
    val stub = new StubSqsClient(List(List(message("not json at all", "bad-1"))))
    new StubbedProcessor(appConfig(), AnalyticsService(repo), stub).start()

    eventually {
      stub.deletedHandles.asScala.toList shouldBe List("bad-1")
    }
    repo.getEventCount.futureValue shouldBe 0L
  }

  it should "leave a message on the queue when tracking it fails" in {
    val repo = new FailingStoreRepository
    val stub = new StubSqsClient(List(List(message(payload("document.edited"), "kept-1"))))
    new StubbedProcessor(appConfig(), AnalyticsService(repo), stub).start()

    eventually {
      stub.receiveCalls.get() should be >= 2
    }
    stub.deletedHandles.asScala.toList shouldBe empty
    repo.getEventCount.futureValue shouldBe 0L
  }

  it should "still have tracked the event when the queue deletion fails" in {
    val repo = MetricsRepository(postgres)
    val stub = new StubSqsClient(List(List(message(payload("document.shared"), "undeletable"))), failDelete = true)
    new StubbedProcessor(appConfig(), AnalyticsService(repo), stub).start()

    eventually {
      repo.getEventCount.futureValue shouldBe 1L
    }
    stub.deletedHandles.asScala.toList shouldBe empty
  }

  it should "keep consuming when an undecodable message cannot be deleted either" in {
    val repo = MetricsRepository(postgres)
    val stub = new StubSqsClient(List(List(message("{", "stuck-1"))), failDelete = true)
    new StubbedProcessor(appConfig(), AnalyticsService(repo), stub).start()

    eventually {
      stub.receiveCalls.get() should be >= 2
    }
    stub.deletedHandles.asScala.toList shouldBe empty
    repo.getEventCount.futureValue shouldBe 0L
  }

  "EventProcessor's SQS client" should "be built for the configured region and endpoint override" in {
    val service = AnalyticsService(MetricsRepository(postgres))
    val plain = new InspectableProcessor(appConfig(), service).client
    plain.serviceName() shouldBe "sqs"
    val overridden = new InspectableProcessor(appConfig(Some("http://localstack:4566")), service).client
    overridden.serviceName() shouldBe "sqs"
    plain.close()
    overridden.close()
  }
