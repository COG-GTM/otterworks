package com.otterworks.analytics.api

import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.model.headers.RawHeader
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.Route
import akka.http.scaladsl.testkit.ScalatestRouteTest
import io.jsonwebtoken.Jwts
import io.jsonwebtoken.security.Keys
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.nio.charset.StandardCharsets

class AuthSpec extends AnyFlatSpec with Matchers with ScalatestRouteTest:

  import TestTokens.*

  private val route = Route.seal(
    concat(
      path("me")(auth.authenticated(u => complete(s"${u.userId}:${u.isAdmin}"))),
      path("admin")(auth.adminOnly(_ => complete("ok"))),
    )
  )

  "JwtAuthenticator" should "accept a valid access token and expose sub and roles" in {
    Get("/me") ~> user("user-1") ~> route ~> check {
      status shouldBe StatusCodes.OK
      responseAs[String] shouldBe "user-1:false"
    }
    Get("/me") ~> admin("boss") ~> route ~> check {
      responseAs[String] shouldBe "boss:true"
    }
  }

  it should "reject requests without a token" in {
    Get("/me") ~> route ~> check { status shouldBe StatusCodes.Unauthorized }
  }

  it should "ignore a spoofed X-User-ID header" in {
    Get("/me") ~> RawHeader("X-User-ID", "victim") ~> route ~> check {
      status shouldBe StatusCodes.Unauthorized
    }
  }

  it should "reject tokens signed with another key" in {
    val otherKey = Keys.hmacShaKeyFor("some-other-secret-that-is-long-enough!!".getBytes(StandardCharsets.UTF_8))
    Get("/me") ~> bearer(token("user-1", signingKey = otherKey)) ~> route ~> check {
      status shouldBe StatusCodes.Unauthorized
    }
  }

  it should "reject expired, refresh and unsigned tokens" in {
    Get("/me") ~> bearer(token("user-1", expiresInSeconds = -60)) ~> route ~> check {
      status shouldBe StatusCodes.Unauthorized
    }
    Get("/me") ~> bearer(token("user-1", tokenType = "refresh")) ~> route ~> check {
      status shouldBe StatusCodes.Unauthorized
    }
    val unsigned = token("user-1", Seq("ADMIN")).split('.').take(2) match
      case Array(_, payload) => s"eyJhbGciOiJub25lIn0.$payload."
    Get("/me") ~> bearer(unsigned) ~> route ~> check {
      status shouldBe StatusCodes.Unauthorized
    }
  }

  it should "reject signed tokens without a type claim" in {
    val untyped = Jwts.builder().subject("admin-1").claim("roles", java.util.List.of("ADMIN"))
      .expiration(java.util.Date.from(java.time.Instant.now().plusSeconds(600)))
      .signWith(Keys.hmacShaKeyFor(Secret.getBytes(StandardCharsets.UTF_8))).compact()
    Get("/me") ~> bearer(untyped) ~> route ~> check { status shouldBe StatusCodes.Unauthorized }
  }

  it should "reject everything when no secret is configured" in {
    val closed = Route.seal(path("me")(AuthDirectives(JwtAuthenticator(None)).authenticated(_ => complete("ok"))))
    Get("/me") ~> user("user-1") ~> closed ~> check { status shouldBe StatusCodes.Unauthorized }
  }

  "adminOnly" should "forbid non-admin callers" in {
    Get("/admin") ~> user("user-1") ~> route ~> check { status shouldBe StatusCodes.Forbidden }
    Get("/admin") ~> admin() ~> route ~> check { status shouldBe StatusCodes.OK }
    Get("/admin") ~> bearer(token("owner-1", Seq("OWNER"))) ~> route ~> check { status shouldBe StatusCodes.OK }
  }
