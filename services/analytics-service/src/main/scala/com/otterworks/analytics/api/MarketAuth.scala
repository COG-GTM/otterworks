package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.model.headers.{HttpChallenge, `WWW-Authenticate`}
import akka.http.scaladsl.server.{Directive1, StandardRoute}
import akka.http.scaladsl.server.Directives.*
import com.otterworks.analytics.config.AuthConfig
import spray.json.*

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import scala.util.Try

/** Caller identity taken from a bearer token whose signature this service verified itself. */
final case class VerifiedCaller(userId: String, roles: Set[String])

/**
 * Verifies the auth-service's HMAC-signed access tokens (HS256/384/512, `type=access`,
 * unexpired, non-empty `sub`). Gateway-forwarded identity headers are not trusted: the
 * backend port can be reached without passing through the gateway.
 */
final class JwtVerifier(secret: String, now: () => Long = () => Instant.now().getEpochSecond):
  private val secretBytes = secret.getBytes(StandardCharsets.UTF_8)
  private val algorithms = Map("HS256" -> "HmacSHA256", "HS384" -> "HmacSHA384", "HS512" -> "HmacSHA512")

  def verify(token: String): Either[String, VerifiedCaller] =
    token.split('.') match
      case Array(header, payload, signature) =>
        for
          headerJson <- decodeJson(header).toRight("malformed token header")
          alg <- headerJson.fields.get("alg").collect { case JsString(a) => a }.toRight("missing alg")
          macAlg <- algorithms.get(alg).toRight(s"unsupported alg $alg")
          sig <- decode(signature).toRight("malformed signature")
          _ <- Either.cond(validSignature(macAlg, s"$header.$payload", sig), (), "invalid signature")
          claims <- decodeJson(payload).toRight("malformed token payload")
          caller <- callerFrom(claims)
        yield caller
      case _ => Left("malformed token")

  private def validSignature(macAlg: String, signingInput: String, signature: Array[Byte]): Boolean =
    val mac = Mac.getInstance(macAlg)
    mac.init(new SecretKeySpec(secretBytes, macAlg))
    MessageDigest.isEqual(mac.doFinal(signingInput.getBytes(StandardCharsets.US_ASCII)), signature)

  private def callerFrom(claims: JsObject): Either[String, VerifiedCaller] =
    val f = claims.fields
    for
      _ <- Either.cond(f.get("type").contains(JsString("access")), (), "not an access token")
      exp <- f.get("exp").collect { case JsNumber(n) => n.toLong }.toRight("missing exp")
      _ <- Either.cond(exp > now(), (), "token expired")
      sub <- f.get("sub").collect { case JsString(s) if s.trim.nonEmpty => s.trim }.toRight("missing sub")
    yield
      val roles = f.get("roles") match
        case Some(JsArray(values)) => values.collect { case JsString(r) => r.trim.toUpperCase }.filter(_.nonEmpty).toSet
        case _                     => Set.empty[String]
      VerifiedCaller(sub, roles)

  private def decode(segment: String): Option[Array[Byte]] =
    Try(Base64.getUrlDecoder.decode(segment)).toOption

  private def decodeJson(segment: String): Option[JsObject] =
    decode(segment).flatMap(bytes => Try(new String(bytes, StandardCharsets.UTF_8).parseJson.asJsObject).toOption)

/**
 * Role checks for the margins/market routes, which expose supplier cost data and accept
 * price observations that feed margin computation. Fails closed (503) when no JWT secret
 * is configured.
 */
final class MarketAuth(verifier: Option[JwtVerifier], readRoles: Set[String], writeRoles: Set[String]):

  /** May read margins, cost breakdowns and market prices. */
  val reader: Directive1[VerifiedCaller] = requireAnyRole(readRoles)

  /** May write market observations (implies nothing about read access). */
  val writer: Directive1[VerifiedCaller] = requireAnyRole(writeRoles)

  private def requireAnyRole(allowed: Set[String]): Directive1[VerifiedCaller] =
    verifier match
      case None =>
        complete(StatusCodes.ServiceUnavailable, error("authentication is not configured")).toDirective[Tuple1[VerifiedCaller]]
      case Some(v) =>
        optionalHeaderValueByName("Authorization").flatMap { header =>
          bearerToken(header).toRight("missing bearer token").flatMap(v.verify) match
            case Left(_) =>
              StandardRoute(
                respondWithHeader(`WWW-Authenticate`(HttpChallenge("Bearer", Some("otterworks")))) {
                  complete(StatusCodes.Unauthorized, error("authentication required"))
                }
              ).toDirective[Tuple1[VerifiedCaller]]
            case Right(caller) if caller.roles.exists(allowed.contains) =>
              provide(caller)
            case Right(_) =>
              complete(StatusCodes.Forbidden, error("insufficient role")).toDirective[Tuple1[VerifiedCaller]]
        }

  private def bearerToken(header: Option[String]): Option[String] =
    header.map(_.trim.split("\\s+", 2)).collect {
      case Array(scheme, token) if scheme.equalsIgnoreCase("bearer") && token.nonEmpty => token
    }

  private def error(message: String): JsObject = JsObject("error" -> JsString(message))

object MarketAuth:
  def apply(config: AuthConfig): MarketAuth =
    new MarketAuth(config.jwtSecret.map(new JwtVerifier(_)), config.marginsReadRoles, config.marketWriteRoles)
