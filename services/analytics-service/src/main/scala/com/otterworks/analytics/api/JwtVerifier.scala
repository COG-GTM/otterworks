package com.otterworks.analytics.api

import spray.json.*

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import scala.util.Try

/** Claims analytics-service relies on from an auth-service access token. */
final case class VerifiedToken(subject: String, roles: Set[String])

/**
 * Verifies auth-service access tokens (HS256/384/512 signed with the shared
 * JWT_SECRET, the same key the gateway validates with). Only signed, unexpired
 * access tokens with a subject are accepted; refresh tokens are refused.
 */
final class JwtVerifier(secret: String, clock: () => Instant = () => Instant.now()):
  require(secret.nonEmpty, "JWT secret must not be empty")

  private val key = secret.getBytes(StandardCharsets.UTF_8)
  private val algorithms = Map("HS256" -> "HmacSHA256", "HS384" -> "HmacSHA384", "HS512" -> "HmacSHA512")
  private val decoder = Base64.getUrlDecoder

  def verify(token: String): Option[VerifiedToken] =
    token.split('.') match
      case Array(header, payload, signature) =>
        for
          headerJson <- decodeJson(header)
          alg <- stringField(headerJson, "alg")
          macAlg <- algorithms.get(alg)
          given <- Try(decoder.decode(signature)).toOption
          if MessageDigest.isEqual(sign(macAlg, s"$header.$payload"), given)
          claims <- decodeJson(payload)
          if notExpired(claims)
          if stringField(claims, "type").forall(_ == "access")
          subject <- stringField(claims, "sub").orElse(stringField(claims, "user_id")).map(_.trim).filter(_.nonEmpty)
        yield VerifiedToken(subject, roles(claims))
      case _ => None

  private def sign(macAlg: String, input: String): Array[Byte] =
    val mac = Mac.getInstance(macAlg)
    mac.init(SecretKeySpec(key, macAlg))
    mac.doFinal(input.getBytes(StandardCharsets.US_ASCII))

  private def decodeJson(part: String): Option[JsObject] =
    Try(new String(decoder.decode(part), StandardCharsets.UTF_8).parseJson.asJsObject).toOption

  private def stringField(obj: JsObject, name: String): Option[String] =
    obj.fields.get(name).collect { case JsString(v) => v }

  private def notExpired(claims: JsObject): Boolean =
    claims.fields.get("exp") match
      case Some(JsNumber(exp)) => Instant.ofEpochSecond(exp.toLong).isAfter(clock())
      case _                   => false

  private def roles(claims: JsObject): Set[String] =
    claims.fields.get("roles") match
      case Some(JsArray(values)) =>
        values.collect { case JsString(r) => r.trim.toUpperCase }.filter(_.nonEmpty).toSet
      case _ => Set.empty
