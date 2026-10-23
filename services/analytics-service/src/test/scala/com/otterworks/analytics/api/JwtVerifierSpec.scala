package com.otterworks.analytics.api

import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

class JwtVerifierSpec extends AnyFlatSpec with Matchers:
  private val verifier = JwtVerifier("verifier-secret")

  "JwtVerifier" should "accept a signed access token and normalize roles" in {
    verifier.verify(TestJwt.sign("verifier-secret", "user-1", Seq("user", " Admin "))) shouldBe
      Some(VerifiedToken("user-1", Set("USER", "ADMIN")))
  }

  it should "reject tokens signed with another key, expired, refresh, unsigned, or malformed" in {
    Seq(
      TestJwt.sign("other-secret", "user-1", Seq("ADMIN")),
      TestJwt.sign("verifier-secret", "user-1", Seq("ADMIN"), expiresInSeconds = -1),
      TestJwt.sign("verifier-secret", "user-1", Seq("ADMIN"), tokenType = "refresh"),
      TestJwt.unsigned("user-1", Seq("ADMIN")),
      "not-a-jwt",
      "a.b.c",
      ""
    ).foreach { t => withClue(t) { verifier.verify(t) shouldBe None } }
  }

  it should "reject a token whose payload was altered after signing" in {
    val Array(h, _, sig) = TestJwt.sign("verifier-secret", "user-1", Seq("USER")).split('.')
    val Array(_, adminPayload, _) = TestJwt.sign("verifier-secret", "user-1", Seq("ADMIN")).split('.')
    verifier.verify(s"$h.$adminPayload.$sig") shouldBe None
  }
