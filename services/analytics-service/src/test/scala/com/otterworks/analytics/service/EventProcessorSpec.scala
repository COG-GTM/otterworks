package com.otterworks.analytics.service

import akka.actor.typed.ActorSystem
import akka.actor.typed.scaladsl.Behaviors
import akka.http.scaladsl.Http
import akka.http.scaladsl.model.{ContentType, HttpCharsets, HttpEntity, HttpResponse, MediaType, StatusCode, StatusCodes}
import akka.http.scaladsl.server.Directives.*
import com.otterworks.analytics.config.*
import com.otterworks.analytics.model.*
import com.otterworks.analytics.repository.{InMemoryMetricsRepository, MetricsRepository}
import org.scalatest.BeforeAndAfterAll
import org.scalatest.concurrent.{Eventually, ScalaFutures}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import spray.json.*

import java.security.MessageDigest
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.{AtomicBoolean, AtomicInteger}
import scala.concurrent.{Await, ExecutionContext, Future}
import scala.concurrent.duration.*
import scala.jdk.CollectionConverters.*

/** Drives EventProcessor against an in-process fake of the SQS JSON protocol. */
class EventProcessorSpec extends AnyFlatSpec with Matchers with ScalaFutures with Eventually with BeforeAndAfterAll:

  given PatienceConfig = PatienceConfig(timeout = Span(20, Seconds), interval = Span(100, Millis))

  override def beforeAll(): Unit =
    System.setProperty("aws.accessKeyId", "test")
    System.setProperty("aws.secretAccessKey", "test")

  private val pgCfg = PostgresConfig("jdbc:postgresql://localhost:5432/test", "test", "test", 2)
  private val amzJson = ContentType(MediaType.applicationWithFixedCharset("x-amz-json-1.0", HttpCharsets.`UTF-8`))

  private final class FakeSqs:
    val pending = new ConcurrentLinkedQueue[(String, String)]()
    val deleted = new ConcurrentLinkedQueue[String]()
    val deleteAttempts = new ConcurrentLinkedQueue[String]()
    val receives = new AtomicInteger(0)
    val failNextReceive = new AtomicBoolean(false)

    private def md5(s: String): String =
      MessageDigest.getInstance("MD5").digest(s.getBytes("UTF-8")).map("%02x".format(_)).mkString

    private def json(status: StatusCode, body: JsValue): HttpResponse =
      HttpResponse(status, entity = HttpEntity(amzJson, body.compactPrint))

    private def error(code: String): HttpResponse =
      json(StatusCodes.BadRequest, JsObject("__type" -> JsString(s"com.amazonaws.sqs#$code"), "message" -> JsString("fake failure")))

    val route = post {
      headerValueByName("X-Amz-Target") { target =>
        entity(as[String]) { body =>
          target match
            case "AmazonSQS.ReceiveMessage" =>
              receives.incrementAndGet()
              if failNextReceive.getAndSet(false) then complete(error("InvalidParameterValue"))
              else
                val batch = Iterator.continually(Option(pending.poll())).takeWhile(_.isDefined).flatten.toList
                val msgs = batch.zipWithIndex.map { case ((handle, msgBody), i) =>
                  JsObject(
                    "MessageId" -> JsString(s"m-$i-$handle"),
                    "ReceiptHandle" -> JsString(handle),
                    "MD5OfBody" -> JsString(md5(msgBody)),
                    "Body" -> JsString(msgBody)
                  )
                }
                complete(json(StatusCodes.OK, JsObject("Messages" -> JsArray(msgs.toVector))))
            case "AmazonSQS.DeleteMessage" =>
              val handle = body.parseJson.asJsObject.fields("ReceiptHandle").convertTo[String](using DefaultJsonProtocol.StringJsonFormat)
              deleteAttempts.add(handle)
              if handle.startsWith("fail-delete") then complete(error("ReceiptHandleIsInvalid"))
              else
                deleted.add(handle)
                complete(json(StatusCodes.OK, JsObject()))
            case other => complete(error(s"Unsupported:$other"))
        }
      }
    }

  private object FailingStore extends MetricsRepository:
    private def boom[T]: Future[T] = Future.failed(new RuntimeException("store down"))
    def storeEvent(event: AnalyticsEvent): Future[Unit] = boom
    def getDashboardSummary(period: String): Future[DashboardSummary] = boom
    def getUserActivity(userId: String): Future[UserActivity] = boom
    def getDocumentStats(documentId: String): Future[DocumentStats] = boom
    def getTopContent(contentType: String, period: String, limit: Int): Future[TopContentResponse] = boom
    def getActiveUsers(period: String): Future[ActiveUsersResponse] = boom
    def getStorageUsage(userId: Option[String]): Future[StorageUsageResponse] = boom
    def getExportData(period: String): Future[List[Map[String, String]]] = boom
    def getEventCount: Future[Long] = boom

  private def run(repoFor: ExecutionContext => MetricsRepository)(
      setup: FakeSqs => Unit
  )(verify: (FakeSqs, MetricsRepository, ExecutionContext) => Unit): Unit =
    given system: ActorSystem[Nothing] = ActorSystem(Behaviors.empty, "event-processor-spec")
    given ec: ExecutionContext = system.executionContext
    try
      val fake = FakeSqs()
      setup(fake)
      val binding = Await.result(Http().newServerAt("127.0.0.1", 0).bind(fake.route), 10.seconds)
      val base = s"http://127.0.0.1:${binding.localAddress.getPort}"
      val config = AppConfig(
        S3Config("lake"),
        SqsConfig(s"$base/000000000000/analytics-events"),
        AwsConfig("us-east-1", Some(base)),
        pgCfg,
        RepositoryConfig("in-memory"),
        ServerConfig("127.0.0.1", 0)
      )
      val repo = repoFor(ec)
      EventProcessor(config, AnalyticsService(repo)).start()
      verify(fake, repo, ec)
    finally
      system.terminate()
      Await.result(system.whenTerminated, 20.seconds): Unit

  private def inMemory(ec: ExecutionContext): MetricsRepository = new InMemoryMetricsRepository(pgCfg)(using ec)

  private val validBody =
    """{"eventType":"document.created","userId":"user-7","resourceId":"doc-7","resourceType":"document","metadata":{"title":"Q3"}}"""
  private val noMetadataBody =
    """{"eventType":"file.uploaded","userId":"user-7","resourceId":"file-1","resourceType":"file"}"""

  "EventProcessor" should "track decodable SQS messages and delete them from the queue" in {
    run(inMemory) { fake =>
      fake.pending.add("h-1" -> validBody)
      fake.pending.add("h-2" -> noMetadataBody)
    } { (fake, repo, ec) =>
      eventually {
        fake.deleted.asScala.toSet shouldBe Set("h-1", "h-2")
      }
      val activity = repo.getUserActivity("user-7").futureValue
      activity.totalEvents shouldBe 2
      activity.recentEvents.map(_.eventType).toSet shouldBe Set("document.created", "file.uploaded")
      activity.recentEvents.map(_.resourceId).toSet shouldBe Set("doc-7", "file-1")
    }
  }

  it should "delete undecodable messages without tracking anything" in {
    run(inMemory) { fake =>
      fake.pending.add("bad-1" -> "not json")
      fake.pending.add("bad-2" -> """{"eventType":"document.created"}""")
    } { (fake, repo, _) =>
      eventually {
        fake.deleted.asScala.toSet shouldBe Set("bad-1", "bad-2")
      }
      repo.getEventCount.futureValue shouldBe 0L
    }
  }

  it should "keep consuming when deleting a message fails" in {
    run(inMemory) { fake =>
      fake.pending.add("fail-delete-good" -> validBody)
      fake.pending.add("fail-delete-bad" -> "{")
      fake.pending.add("h-ok" -> noMetadataBody)
    } { (fake, repo, _) =>
      eventually {
        fake.deleteAttempts.asScala.toSet shouldBe Set("fail-delete-good", "fail-delete-bad", "h-ok")
        fake.deleted.asScala.toList shouldBe List("h-ok")
        repo.getEventCount.futureValue shouldBe 2L
      }
    }
  }

  it should "leave the message on the queue when the event store fails" in {
    run(_ => FailingStore) { fake =>
      fake.pending.add("h-store-fails" -> validBody)
    } { (fake, _, _) =>
      eventually {
        fake.receives.get() should be >= 1
        fake.pending.isEmpty shouldBe true
      }
      Thread.sleep(500)
      fake.deleteAttempts shouldBe empty
    }
  }

  it should "retry on the next tick after a failed receive" in {
    run(inMemory) { fake =>
      fake.failNextReceive.set(true)
      fake.pending.add("h-after-retry" -> validBody)
    } { (fake, repo, _) =>
      eventually(timeout(Span(20, Seconds))) {
        fake.receives.get() should be >= 2
        fake.deleted.asScala.toList shouldBe List("h-after-retry")
      }
      repo.getEventCount.futureValue shouldBe 1L
    }
  }
