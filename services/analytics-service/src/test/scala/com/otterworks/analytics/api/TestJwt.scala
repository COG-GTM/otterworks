package com.otterworks.analytics.api

import spray.json.*

import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** Mints auth-service-shaped HS256 access tokens for tests. */
object TestJwt:
  private val encoder = Base64.getUrlEncoder.withoutPadding

  private def b64(json: JsValue): String = encoder.encodeToString(json.compactPrint.getBytes(StandardCharsets.UTF_8))

  private def claims(subject: String, roles: Seq[String], expiresInSeconds: Long, tokenType: String): JsObject =
    JsObject(
      "sub" -> JsString(subject),
      "roles" -> JsArray(roles.map(JsString(_)).toVector),
      "type" -> JsString(tokenType),
      "exp" -> JsNumber(Instant.now().getEpochSecond + expiresInSeconds)
    )

  def sign(
      secret: String,
      subject: String,
      roles: Seq[String],
      expiresInSeconds: Long = 900,
      tokenType: String = "access"
  ): String =
    val input = s"${b64(JsObject("alg" -> JsString("HS256"), "typ" -> JsString("JWT")))}.${b64(claims(subject, roles, expiresInSeconds, tokenType))}"
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"))
    s"$input.${encoder.encodeToString(mac.doFinal(input.getBytes(StandardCharsets.US_ASCII)))}"

  def unsigned(subject: String, roles: Seq[String]): String =
    s"${b64(JsObject("alg" -> JsString("none")))}.${b64(claims(subject, roles, 900, "access"))}."
