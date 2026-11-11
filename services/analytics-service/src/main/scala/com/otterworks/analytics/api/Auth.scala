package com.otterworks.analytics.api

import akka.http.scaladsl.server.Directive1
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.directives.Credentials
import io.jsonwebtoken.{Claims, JwtException, JwtParser, Jwts}
import io.jsonwebtoken.security.Keys
import org.slf4j.LoggerFactory

import java.nio.charset.StandardCharsets
import scala.jdk.CollectionConverters.*
import scala.util.Try

/** Caller identity taken from a verified access token. */
final case class AuthenticatedUser(userId: String, roles: Set[String]):
  def isAdmin: Boolean = roles.exists(AuthenticatedUser.AdminRoles.contains)

object AuthenticatedUser:
  val AdminRoles: Set[String] = Set("ADMIN", "OWNER", "SUPER_ADMIN")

/**
 * Verifies the HMAC-signed JWTs issued by auth-service (the same token the
 * API gateway validates and forwards in the Authorization header). The
 * service never trusts caller-supplied identity headers or ids; with no
 * secret configured every request is rejected.
 */
class JwtAuthenticator(secret: Option[String]):

  private val logger = LoggerFactory.getLogger(getClass)

  private val parser: Option[JwtParser] =
    secret.map(_.trim).filter(_.nonEmpty).flatMap { s =>
      Try(Jwts.parser().verifyWith(Keys.hmacShaKeyFor(s.getBytes(StandardCharsets.UTF_8))).build())
        .fold(
          ex =>
            logger.error("JWT_SECRET is unusable ({}); analytics API requests will be rejected", ex.getMessage)
            None,
          Some(_)
        )
    }

  def isConfigured: Boolean = parser.isDefined

  def verify(token: String): Option[AuthenticatedUser] =
    parser.flatMap { p =>
      try toUser(p.parseSignedClaims(token).getPayload)
      catch
        case ex: JwtException =>
          logger.debug("JWT rejected: {}", ex.getMessage)
          None
        case _: IllegalArgumentException => None
    }

  def authenticate(credentials: Credentials): Option[AuthenticatedUser] = credentials match
    case Credentials.Provided(token) => verify(token)
    case _                            => None

  private def toUser(claims: Claims): Option[AuthenticatedUser] =
    if !Option(claims.get("type", classOf[String])).contains("access") then None
    else
      val userId = Option(claims.getSubject).orElse(Option(claims.get("user_id", classOf[String]))).map(_.trim)
      userId.filter(_.nonEmpty).map(id => AuthenticatedUser(id, roles(claims)))

  private def roles(claims: Claims): Set[String] =
    val raw: Seq[Any] = claims.get("roles") match
      case list: java.util.Collection[?] => list.asScala.toSeq
      case _                             => Option(claims.get("role")).toSeq
    raw.collect { case r if r != null => r.toString.trim.toUpperCase }.filter(_.nonEmpty).toSet

/** Akka HTTP directives that bind requests to the verified caller. */
class AuthDirectives(authenticator: JwtAuthenticator):

  val Realm = "otterworks-analytics"

  /** 401 unless the request carries a valid bearer access token. */
  val authenticated: Directive1[AuthenticatedUser] =
    authenticateOAuth2(Realm, authenticator.authenticate)

  /** 403 unless the caller holds an admin role. */
  val adminOnly: Directive1[AuthenticatedUser] =
    authenticated.flatMap(user => authorize(user.isAdmin).tmap(_ => user))

  /** 403 unless the caller is `userId` or an admin. */
  def selfOrAdmin(userId: String): Directive1[AuthenticatedUser] =
    authenticated.flatMap(user => authorize(user.isAdmin || user.userId == userId).tmap(_ => user))
