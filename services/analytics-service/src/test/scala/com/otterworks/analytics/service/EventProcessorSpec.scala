package com.otterworks.analytics.service

import akka.actor.testkit.typed.scaladsl.ActorTestKit
import akka.actor.typed.ActorSystem
import akka.http.scaladsl.Http
import akka.http.scaladsl.model.{ContentTypes, HttpEntity, HttpResponse, StatusCode, StatusCodes}
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.Route
import com.otterworks.analytics.config.*
import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.{InMemoryMetricsRepository, MetricsRepository}
import org.scalatest.BeforeAndAfterAll
import org.scalatest.concurrent.{Eventually, ScalaFutures}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import spray.json.*

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicInteger
import scala.concurrent.duration.*
import scala.concurrent.{Await, ExecutionContext, Future}
import scala.jdk.CollectionConverters.*

/**
 * Drives [[EventProcessor]] against a stand-in SQS endpoint (the AWS SDK's JSON
 * protocol served by a local akka-http server), so the polling loop, the decode
 * path and every failure branch are exercised without AWS or LocalStack.
 */
class EventProcessorSpec extends AnyFlatSpec with Matchers with ScalaFutures with Eventually with BeforeAndAfterAll:

  private val testKit = ActorTestKit("event-processor-spec")
  private given system: ActorSystem[Nothing] = testKit.system
  private given ec: ExecutionContext = testKit.system.executionContext

  given PatienceConfig = PatienceConfig(timeout = Span(20, Seconds), interval = Span(200, Millis))

  private val bindings = new ConcurrentLinkedQueue[Http.ServerBinding]()

  override def beforeAll(): Unit =
    super.beforeAll()
    // The processor builds its client with the DefaultCredentialsProvider; system
    // properties keep the chain off the instance-metadata endpoint.
    System.setProperty("aws.accessKeyId", "test-access-key")
    System.setProperty("aws.secretAccessKey", "test-secret-key")

  override def afterAll(): Unit =
    System.clearProperty("aws.accessKeyId")
    System.clearProperty("aws.secretAccessKey")
    bindings.asScala.foreach(b => Await.ready(b.unbind(), 5.seconds))
    testKit.shutdownTestKit()
    super.afterAll()

  private def md5Hex(s: String): String =
    MessageDigest.getInstance("MD5").digest(s.getBytes(StandardCharsets.UTF_8)).map("%02x".format(_)).mkString

  private def jsonResponse(status: StatusCode, body: String): HttpResponse =
    HttpResponse(status, entity = HttpEntity(ContentTypes.`application/json`, body))

  private def receiveResponse(messages: Seq[(String, String)]): HttpResponse =
    val encoded = messages.map { case (receiptHandle, body) =>
      JsObject(
        "MessageId" -> JsString(s"msg-$receiptHandle"),
        "ReceiptHandle" -> JsString(receiptHandle),
        "MD5OfBody" -> JsString(md5Hex(body)),
        "Body" -> JsString(body)
      )
    }
    jsonResponse(StatusCodes.OK, JsObject("Messages" -> JsArray(encoded.toVector)).compactPrint)

  private val emptyReceiveResponse = jsonResponse(StatusCodes.OK, "{}")

  private val sqsErrorResponse =
    jsonResponse(
      StatusCodes.BadRequest,
      JsObject(
        "__type" -> JsString("com.amazonaws.sqs#QueueDoesNotExist"),
        "message" -> JsString("The specified queue does not exist")
      ).compactPrint
    )

  /** Records the receipt handles the processor asked SQS to delete. */
  private class FakeSqs(
      receive: Int => HttpResponse,
      deleteResponse: HttpResponse = jsonResponse(StatusCodes.OK, "{}")
  ):
    val receiveCount = new AtomicInteger(0)
    val deleted = new ConcurrentLinkedQueue[String]()

    val route: Route = post {
      extractRequest { request =>
        val operation = request.headers.find(_.is("x-amz-target")).map(_.value.split('.').last).getOrElse("")
        entity(as[String]) { body =>
          operation match
            case "ReceiveMessage" => complete(receive(receiveCount.incrementAndGet()))
            case "DeleteMessage" =>
              body.parseJson.asJsObject.fields("ReceiptHandle") match
                case JsString(handle) => deleted.add(handle)
                case other            => deleted.add(other.compactPrint)
              complete(deleteResponse)
            case other => complete(StatusCodes.BadRequest, s"unexpected SQS operation: $other")
        }
      }
    }

    def deletedHandles: List[String] = deleted.asScala.toList

  /** A repository whose writes always fail, standing in for an unreachable store. */
  private class FailingRepository extends MetricsRepository:
    val storeAttempts = new AtomicInteger(0)
    private def boom[A]: Future[A] = Future.failed(new RuntimeException("metrics store unreachable"))
    def storeEvent(event: AnalyticsEvent): Future[Unit] =
      storeAttempts.incrementAndGet()
      boom
    def getDashboardSummary(period: String): Future[DashboardSummary] = boom
    def getUserActivity(userId: String): Future[UserActivity] = boom
    def getDocumentStats(documentId: String): Future[DocumentStats] = boom
    def getTopContent(contentType: String, period: String, limit: Int): Future[TopContentResponse] = boom
    def getActiveUsers(period: String): Future[ActiveUsersResponse] = boom
    def getStorageUsage(userId: Option[String]): Future[StorageUsageResponse] = boom
    def getExportData(period: String): Future[List[Map[String, String]]] = boom
    def getEventCount: Future[Long] = boom

  /** Bind the fake endpoint and start a processor wired to the given metrics store. */
  private def startProcessor(fake: FakeSqs, repository: MetricsRepository): AnalyticsService =
    val binding = Http().newServerAt("localhost", 0).bind(fake.route).futureValue
    bindings.add(binding)
    val endpoint = s"http://localhost:${binding.localAddress.getPort}"
    val config = AppConfig(
      s3 = S3Config("test-lake"),
      sqs = SqsConfig(s"$endpoint/000000000000/analytics-events"),
      aws = AwsConfig("us-east-1", Some(endpoint)),
      postgres = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2),
      repository = RepositoryConfig("in-memory"),
      server = ServerConfig("localhost", 0)
    )
    val service = AnalyticsService(repository)
    EventProcessor(config, service).start()
    service

  private def startProcessor(fake: FakeSqs): AnalyticsService =
    startProcessor(fake, new InMemoryMetricsRepository(PostgresConfig("jdbc:postgresql://x/y", "u", "p", 1)))

  private val validBody =
    JsObject(
      "eventType" -> JsString("document.created"),
      "userId" -> JsString("user-42"),
      "resourceId" -> JsString("doc-7"),
      "resourceType" -> JsString("document"),
      "metadata" -> JsObject("title" -> JsString("Quarterly plan"))
    ).compactPrint

  "EventProcessor" should "track events polled from SQS and delete them from the queue" in {
    val fake = new FakeSqs({
      case 1 => receiveResponse(Seq("rh-1" -> validBody))
      case _ => emptyReceiveResponse
    })
    val service = startProcessor(fake)

    eventually {
      service.getEventCount.futureValue shouldBe 1L
      fake.deletedHandles shouldBe List("rh-1")
    }

    val activity = service.getUserActivity("user-42").futureValue
    activity.totalEvents shouldBe 1L
    activity.documentsCreated shouldBe 1L
    activity.recentEvents.map(_.resourceId) shouldBe List("doc-7")
  }

  it should "process every message of a multi-message batch" in {
    val bodies = (1 to 3).map { i =>
      s"rh-batch-$i" -> JsObject(
        "eventType" -> JsString("file.uploaded"),
        "userId" -> JsString(s"user-$i"),
        "resourceId" -> JsString(s"file-$i"),
        "resourceType" -> JsString("file")
      ).compactPrint
    }
    val fake = new FakeSqs({
      case 1 => receiveResponse(bodies)
      case _ => emptyReceiveResponse
    })
    val service = startProcessor(fake)

    eventually {
      service.getEventCount.futureValue shouldBe 3L
      fake.deletedHandles.sorted shouldBe List("rh-batch-1", "rh-batch-2", "rh-batch-3")
    }
  }

  it should "drop an undecodable message instead of letting it block the queue" in {
    val fake = new FakeSqs({
      case 1 => receiveResponse(Seq("rh-bad" -> """{"not":"an event"}"""))
      case 2 => receiveResponse(Seq("rh-good" -> validBody))
      case _ => emptyReceiveResponse
    })
    val service = startProcessor(fake)

    eventually {
      fake.deletedHandles should contain("rh-bad")
      service.getEventCount.futureValue shouldBe 1L
    }
    fake.deletedHandles should contain("rh-good")
  }

  it should "keep polling after a failed receive" in {
    val fake = new FakeSqs({
      case 1 => sqsErrorResponse
      case 2 => receiveResponse(Seq("rh-after-failure" -> validBody))
      case _ => emptyReceiveResponse
    })
    val service = startProcessor(fake)

    eventually {
      fake.receiveCount.get() should be >= 2
      service.getEventCount.futureValue shouldBe 1L
      fake.deletedHandles shouldBe List("rh-after-failure")
    }
  }

  it should "still store the event when the queue rejects the delete" in {
    val fake = new FakeSqs(
      {
        case 1 => receiveResponse(Seq("rh-undeletable" -> validBody))
        case _ => emptyReceiveResponse
      },
      deleteResponse = sqsErrorResponse
    )
    val service = startProcessor(fake)

    eventually {
      service.getEventCount.futureValue shouldBe 1L
      fake.deletedHandles shouldBe List("rh-undeletable")
    }
  }

  it should "log and keep polling when the metrics store rejects the event" in {
    val fake = new FakeSqs({
      case 1 => receiveResponse(Seq("rh-unstorable" -> validBody))
      case _ => emptyReceiveResponse
    })
    val repository = new FailingRepository
    startProcessor(fake, repository)

    eventually {
      repository.storeAttempts.get() shouldBe 1
      fake.receiveCount.get() should be >= 2
    }
    // The event never made it to the store, so the message is left on the queue.
    fake.deletedHandles shouldBe empty
  }

  it should "keep polling when an undecodable message cannot be deleted either" in {
    val fake = new FakeSqs(
      {
        case 1 => receiveResponse(Seq("rh-stuck" -> "this is not json at all"))
        case _ => emptyReceiveResponse
      },
      deleteResponse = sqsErrorResponse
    )
    val service = startProcessor(fake)

    eventually {
      fake.deletedHandles shouldBe List("rh-stuck")
      fake.receiveCount.get() should be >= 2
    }
    service.getEventCount.futureValue shouldBe 0L
  }
