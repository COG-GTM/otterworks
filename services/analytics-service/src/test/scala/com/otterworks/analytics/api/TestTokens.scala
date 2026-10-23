package com.otterworks.analytics.api

import spray.json.*

import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** Builds HS256 tokens shaped like the auth-service's access tokens. */
object TestTokens:
  val Secret = "analytics-test-secret-at-least-32-bytes-long"

  def access(
      subject: String,
      roles: Seq[String],
      secret: String = Secret,
      tokenType: String = "access",
      expiresAt: Long = Instant.now().getEpochSecond + 900,
  ): String =
    sign(
      JsObject(
        "sub" -> JsString(subject),
        "roles" -> JsArray(roles.map(JsString(_)).toVector),
        "type" -> JsString(tokenType),
        "exp" -> JsNumber(expiresAt),
      ),
      secret,
    )

  def sign(claims: JsObject, secret: String = Secret, alg: String = "HS256"): String =
    val header = encode(JsObject("alg" -> JsString(alg), "typ" -> JsString("JWT")).compactPrint)
    val payload = encode(claims.compactPrint)
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"))
    val signature = Base64.getUrlEncoder.withoutPadding.encodeToString(
      mac.doFinal(s"$header.$payload".getBytes(StandardCharsets.US_ASCII))
    )
    s"$header.$payload.$signature"

  def encode(json: String): String =
    Base64.getUrlEncoder.withoutPadding.encodeToString(json.getBytes(StandardCharsets.UTF_8))
