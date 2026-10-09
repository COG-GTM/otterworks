package com.otterworks.analytics.service

import akka.actor.ActorSystem
import akka.http.scaladsl.Http
import akka.http.scaladsl.model.{HttpResponse, StatusCodes}
import akka.http.scaladsl.server.Directives.*
import akka.pattern.after
import com.otterworks.analytics.api.Caller
import org.scalatest.BeforeAndAfterAll
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import java.util.concurrent.ConcurrentLinkedQueue
import scala.concurrent.{Await, Future}
import scala.concurrent.duration.DurationInt

class DocumentServiceAccessSpec extends AnyFlatSpec with Matchers with ScalaFutures with BeforeAndAfterAll:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(50, Millis))
  given system: ActorSystem = ActorSystem("document-access-spec")

  private val ownedDoc = "11111111-1111-1111-1111-111111111111"
  private val otherDoc = "22222222-2222-2222-2222-222222222222"
  private val missingDoc = "33333333-3333-3333-3333-333333333333"
  private val slowDoc = "44444444-4444-4444-4444-444444444444"
  private val seen = ConcurrentLinkedQueue[(String, Option[String])]()

  private val stub =
    path("api" / "v1" / "documents" / Segment) { id =>
      (optionalHeaderValueByName("X-User-ID") & optionalHeaderValueByName("Authorization")) { (user, auth) =>
        seen.add(id -> user)
        (id, user, auth) match
          case (_, _, None) => complete(HttpResponse(StatusCodes.Unauthorized))
          case (`ownedDoc`, Some("owner"), Some("Bearer owner-token")) => complete(HttpResponse(StatusCodes.OK))
          case (`otherDoc`, _, _) => complete(HttpResponse(StatusCodes.Forbidden))
          case (`slowDoc`, _, _) =>
            val delay = after(2.seconds, system.scheduler)(Future.successful(()))(using system.dispatcher)
            onSuccess(delay) { complete(HttpResponse(StatusCodes.OK)) }
          case _ => complete(HttpResponse(StatusCodes.NotFound))
      }
    }

  private val binding = Await.result(Http().newServerAt("127.0.0.1", 0).bind(stub), 5.seconds)
  private val baseUrl = s"http://127.0.0.1:${binding.localAddress.getPort}/"
  private val access = DocumentServiceAccess(baseUrl, 500.millis)

  override def afterAll(): Unit =
    Await.ready(binding.unbind(), 5.seconds)
    Await.ready(system.terminate(), 10.seconds)

  "DocumentServiceAccess" should "allow a caller document-service lets read the document" in {
    access.canView(Caller("owner", Set("USER"), Some("Bearer owner-token")), ownedDoc).futureValue shouldBe true
  }

  it should "forward the caller's id to document-service" in {
    seen.clear()
    access.canView(Caller("someone", Set.empty, Some("Bearer someone-token")), ownedDoc).futureValue shouldBe false
    seen.peek() shouldBe (ownedDoc -> Some("someone"))
  }

  it should "deny when document-service answers 403 or 404" in {
    access.canView(Caller("owner", Set("USER"), Some("Bearer owner-token")), otherDoc).futureValue shouldBe false
    access.canView(Caller("owner", Set("USER"), Some("Bearer owner-token")), missingDoc).futureValue shouldBe false
  }

  it should "deny non-UUID ids without calling document-service" in {
    seen.clear()
    access.canView(Caller("owner", Set("USER"), Some("Bearer owner-token")), "../admin").futureValue shouldBe false
    access.canView(Caller("owner", Set("USER"), Some("Bearer owner-token")), "doc-1").futureValue shouldBe false
    seen.isEmpty shouldBe true
  }

  it should "fail closed when document-service is slow" in {
    access.canView(Caller("owner", Set("USER"), Some("Bearer owner-token")), slowDoc).futureValue shouldBe false
  }

  it should "fail closed when document-service is unreachable" in {
    val down = DocumentServiceAccess("http://127.0.0.1:1", 500.millis)
    down.canView(Caller("owner", Set("USER"), Some("Bearer owner-token")), ownedDoc).futureValue shouldBe false
  }

  it should "forward the caller's bearer token so document-service can verify it" in {
    access.canView(Caller("owner", Set("USER"), None), ownedDoc).futureValue shouldBe false
    access.canView(Caller("owner", Set("USER"), Some("Bearer forged")), ownedDoc).futureValue shouldBe false
  }
