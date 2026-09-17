package com.otterworks.analytics.service

import akka.actor.typed.ActorSystem
import akka.actor.typed.scaladsl.Behaviors
import akka.http.scaladsl.Http
import akka.http.scaladsl.model.{ContentTypes, HttpEntity, HttpResponse, StatusCode, StatusCodes}
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.Route
import com.otterworks.analytics.config.*
import com.otterworks.analytics.repository.{MetricsRepository, UnavailableMetricsRepository}
import org.scalatest.BeforeAndAfterAll
import org.scalatest.concurrent.Eventually
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import spray.json.*

import java.security.MessageDigest
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicInteger
import scala.concurrent.duration.*
import scala.concurrent.{Await, ExecutionContext, Future}
import scala.jdk.CollectionConverters.*

/**
 * Drives the SQS consumer against a stub queue endpoint (`aws.endpoint-url`),
 * covering the receive/decode/track/delete pipeline plus each failure branch:
 * a queue that errors on receive, a payload that cannot be decoded, and a
 * delete that is rejected.
 */
class EventProcessorSpec extends AnyFlatSpec with Matchers with BeforeAndAfterAll with Eventually:

  given PatienceConfig = PatienceConfig(timeout = Span(30, Seconds), interval = Span(250, Millis))
  given system: ActorSystem[Nothing] = ActorSystem(Behaviors.empty, "event-processor-spec")
  given ExecutionContext = system.executionContext

  private var savedCredentials: Map[String, Option[String]] = Map.empty

  override def beforeAll(): Unit =
    // The SDK resolves credentials before it ever talks to the stub endpoint.
    savedCredentials = List("aws.accessKeyId", "aws.secretAccessKey").map(k => k -> Option(System.getProperty(k))).toMap
    System.setProperty("aws.accessKeyId", "stub-access-key")
    System.setProperty("aws.secretAccessKey", "stub-secret-key")

  override def afterAll(): Unit =
    savedCredentials.foreach {
      case (key, Some(value)) => System.setProperty(key, value)
      case (key, None)        => System.clearProperty(key): Unit
    }
    system.terminate()

  private def md5(value: String): String =
    MessageDigest.getInstance("MD5").digest(value.getBytes("UTF-8")).map("%02x".format(_)).mkString

  private def message(receiptHandle: String, body: String): JsObject =
    JsObject(
      "MessageId" -> JsString(receiptHandle),
      "ReceiptHandle" -> JsString(receiptHandle),
      "MD5OfBody" -> JsString(md5(body)),
      "Body" -> JsString(body)
    )

  private def messagesResponse(messages: JsObject*): HttpResponse =
    jsonResponse(StatusCodes.OK, JsObject("Messages" -> JsArray(messages.toVector)).compactPrint)

  private def jsonResponse(status: StatusCode, body: String): HttpResponse =
    HttpResponse(status, entity = HttpEntity(ContentTypes.`application/json`, body))

  private val queueError = jsonResponse(
    StatusCodes.BadRequest,
    JsObject(
      "__type" -> JsString("com.amazonaws.sqs#InvalidAddress"),
      "message" -> JsString("stub queue rejected the request")
    ).compactPrint
  )

  /** Which SQS operation a request is for, from the JSON-protocol target header or the query body. */
  private def actionOf(target: Option[String], body: String): String =
    target.map(_.split('.').last).getOrElse {
      body.split('&').collectFirst { case p if p.startsWith("Action=") => p.drop("Action=".length) }.getOrElse("")
    }

  /** Bind a stub SQS endpoint; `handler` answers (action, requestBody). */
  private def withStubQueue(handler: (String, String) => HttpResponse)(body: AppConfig => Unit): Unit =
    val route: Route = extractRequest { request =>
      entity(as[String]) { requestBody =>
        val target = request.headers.find(_.lowercaseName == "x-amz-target").map(_.value)
        complete(handler(actionOf(target, requestBody), requestBody))
      }
    }
    val binding = Await.result(Http().newServerAt("127.0.0.1", 0).bind(route), 30.seconds)
    val endpoint = s"http://127.0.0.1:${binding.localAddress.getPort}"
    try
      body(
        AppConfig(
          s3 = S3Config("test-data-lake"),
          sqs = SqsConfig(s"$endpoint/000000000000/analytics-events"),
          aws = AwsConfig("us-east-1", Some(endpoint)),
          postgres = PostgresConfig("", "", "", 1),
          repository = RepositoryConfig("in-memory"),
          server = ServerConfig("127.0.0.1", 0)
        )
      )
    finally Await.result(binding.terminate(3.seconds), 30.seconds): Unit

  private def newService(): AnalyticsService = AnalyticsService(MetricsRepository(PostgresConfig("", "", "", 1)))

  private def receiptHandleOf(requestBody: String): String =
    requestBody.parseJson.asJsObject.fields.get("ReceiptHandle").collect { case JsString(s) => s }.getOrElse("")

  "EventProcessor" should "track decodable messages and delete every message it has seen" in {
    val payload = (userId: String) =>
      JsObject(
        "eventType" -> JsString("document.created"),
        "userId" -> JsString(userId),
        "resourceId" -> JsString("doc-1"),
        "resourceType" -> JsString("document"),
        "metadata" -> JsObject("title" -> JsString("Alpha"))
      ).compactPrint

    val receives = AtomicInteger(0)
    val deleted = ConcurrentLinkedQueue[String]()

    withStubQueue { (action, requestBody) =>
      action match
        case "ReceiveMessage" =>
          if receives.getAndIncrement() > 0 then messagesResponse()
          else
            messagesResponse(
              message("rh-ok", payload("user-1")),
              // metadata is optional on the wire
              message("rh-no-metadata", """{"eventType":"file.uploaded","userId":"user-2","resourceId":"f1","resourceType":"file"}"""),
              message("rh-undecodable", "not-a-json-payload"),
              message("rh-undecodable-delete-rejected", "{\"unexpected\":\"shape\"}"),
              message("rh-delete-rejected", payload("user-3"))
            )
        case "DeleteMessage" =>
          val handle = receiptHandleOf(requestBody)
          deleted.add(handle)
          if handle.endsWith("delete-rejected") then queueError
          else jsonResponse(StatusCodes.OK, "{}")
        case _ => jsonResponse(StatusCodes.OK, "{}")
    } { config =>
      val service = newService()
      EventProcessor(config, service).start()

      eventually {
        Await.result(service.getEventCount, 5.seconds) shouldBe 3L
        deleted.asScala.toSet shouldBe
          Set("rh-ok", "rh-no-metadata", "rh-undecodable", "rh-undecodable-delete-rejected", "rh-delete-rejected")
      }

      val topContent = Await.result(service.getTopContent("all", "7d", 10), 5.seconds)
      topContent.items.map(_.resourceId).toSet shouldBe Set("doc-1", "f1")
    }
  }

  it should "keep polling after the queue rejects a receive" in {
    val receives = AtomicInteger(0)

    withStubQueue { (action, _) =>
      action match
        case "ReceiveMessage" =>
          receives.incrementAndGet()
          queueError
        case _ => jsonResponse(StatusCodes.OK, "{}")
    } { config =>
      EventProcessor(config, newService()).start()

      // The stream survives the failure and ticks again (1s, then every 5s).
      eventually { receives.get() should be >= 2 }
    }
  }

  it should "keep polling when tracking an event fails" in {
    val receives = AtomicInteger(0)
    val deleted = ConcurrentLinkedQueue[String]()

    withStubQueue { (action, requestBody) =>
      action match
        case "ReceiveMessage" =>
          receives.incrementAndGet()
          messagesResponse(message(
            "rh-unstorable",
            """{"eventType":"document.created","userId":"user-1","resourceId":"doc-1","resourceType":"document"}"""
          ))
        case "DeleteMessage" =>
          deleted.add(receiptHandleOf(requestBody))
          jsonResponse(StatusCodes.OK, "{}")
        case _ => jsonResponse(StatusCodes.OK, "{}")
    } { config =>
      EventProcessor(config, AnalyticsService(new UnavailableMetricsRepository)).start()

      eventually { receives.get() should be >= 2 }
      // A message that could not be stored is never acknowledged.
      deleted shouldBe empty
    }
  }
