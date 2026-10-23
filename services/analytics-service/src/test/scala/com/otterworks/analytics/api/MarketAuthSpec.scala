package com.otterworks.analytics.api

import akka.http.scaladsl.model.{ContentTypes, HttpEntity, StatusCodes}
import akka.http.scaladsl.model.headers.{Authorization, OAuth2BearerToken, RawHeader}
import akka.http.scaladsl.server.Route
import akka.http.scaladsl.testkit.ScalatestRouteTest
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import spray.json.*

import java.time.Instant

/**
 * Margins/market routes must refuse callers in-service. The route classes get null
 * backends: a refused request must never reach the repository or the service.
 */
class MarketAuthSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest:

  private val auth = new MarketAuth(Some(new JwtVerifier(TestTokens.Secret)), Set("ADMIN", "OWNER"), Set("ADMIN"))

  private val routes: Route =
    akka.http.scaladsl.server.Directives.concat(
      MarginRoutes(null, null, auth).routes,
      MarketIngestRoutes(null, null, auth).routes,
    )

  private val readPaths = Seq(
    "/api/v1/analytics/margins",
    "/api/v1/analytics/margins/series?sku=SLM-001",
    "/api/v1/analytics/margins/export?format=csv",
    "/api/v1/analytics/market/series",
    "/api/v1/analytics/market/prices?series_code=SALMON_NOK_KG",
    "/api/v1/analytics/market/status",
  )

  private def observations = Post(
    "/api/v1/analytics/market/observations",
    HttpEntity(ContentTypes.`application/json`, """{"observations":[]}"""),
  )

  private def bearer(token: String) = Authorization(OAuth2BearerToken(token))

  "Margins and market routes" should "return 401 without a bearer token" in {
    (readPaths.map(Get(_)) :+ observations).foreach { request =>
      request ~> routes ~> check {
        status shouldBe StatusCodes.Unauthorized
        header("WWW-Authenticate").map(_.value).getOrElse("") should startWith("Bearer")
      }
    }
  }

  they should "ignore gateway identity headers when there is no verified token" in {
    Get("/api/v1/analytics/margins")
      .withHeaders(RawHeader("X-User-ID", "someone"), RawHeader("X-User-Roles", "ADMIN")) ~> routes ~> check {
      status shouldBe StatusCodes.Unauthorized
    }
  }

  they should "return 403 to an authenticated standard user" in {
    val user = bearer(TestTokens.access("u-1", Seq("USER", "EDITOR")))
    (readPaths.map(Get(_)) :+ observations).foreach { request =>
      request.addHeader(user) ~> routes ~> check {
        status shouldBe StatusCodes.Forbidden
        responseAs[String].parseJson shouldBe JsObject("error" -> JsString("insufficient role"))
      }
    }
  }

  they should "keep market writes to the write roles even for a reader" in {
    observations.addHeader(bearer(TestTokens.access("owner-1", Seq("OWNER")))) ~> routes ~> check {
      status shouldBe StatusCodes.Forbidden
    }
  }

  they should "reject forged, expired, refresh and unsigned tokens" in {
    val payload = JsObject(
      "sub" -> JsString("u-1"),
      "roles" -> JsArray(JsString("ADMIN")),
      "type" -> JsString("access"),
      "exp" -> JsNumber(Instant.now().getEpochSecond + 900),
    )
    val unsigned = s"${TestTokens.encode("""{"alg":"none","typ":"JWT"}""")}.${TestTokens.encode(payload.compactPrint)}."
    val tokens = Seq(
      TestTokens.access("u-1", Seq("ADMIN"), secret = "some-other-secret-that-is-32-bytes-long"),
      TestTokens.access("u-1", Seq("ADMIN"), expiresAt = Instant.now().getEpochSecond - 1),
      TestTokens.access("u-1", Seq("ADMIN"), tokenType = "refresh"),
      unsigned,
      "not-a-jwt",
    )
    tokens.foreach { token =>
      Get("/api/v1/analytics/margins").addHeader(bearer(token)) ~> routes ~> check {
        status shouldBe StatusCodes.Unauthorized
      }
    }
  }

  "JwtVerifier" should "accept a valid access token and normalise its roles" in {
    new JwtVerifier(TestTokens.Secret).verify(TestTokens.access("u-9", Seq(" admin ", "USER"))) shouldBe
      Right(VerifiedCaller("u-9", Set("ADMIN", "USER")))
  }

  "MarketAuth without a JWT secret" should "fail closed with 503" in {
    val closed = MarginRoutes(null, null, new MarketAuth(None, Set("ADMIN"), Set("ADMIN"))).routes
    Get("/api/v1/analytics/margins").addHeader(bearer(TestTokens.access("u-1", Seq("ADMIN")))) ~> closed ~> check {
      status shouldBe StatusCodes.ServiceUnavailable
    }
  }
