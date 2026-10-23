package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.{Directive0, Directive1, StandardRoute}
import spray.json.{JsObject, JsString}

/** The authenticated caller of an analytics query route. */
final case class Caller(userId: String, roles: Set[String], authorization: Option[String] = None):
  def isAdmin: Boolean = roles.exists(CallerAuth.AdminRoles.contains)
  def canAccessUser(otherUserId: String): Boolean = isAdmin || otherUserId == userId

/**
 * Authenticates analytics query callers.
 *
 * With a [[JwtVerifier]] (JWT_SECRET configured) the caller must present a valid
 * auth-service access token; identity and roles come from its verified claims,
 * and a gateway X-User-ID that disagrees with the token's subject is rejected.
 * Callers inside the cluster therefore cannot assert an identity by header.
 *
 * Without a verifier the gateway-forwarded X-User-ID is the identity and no
 * caller is treated as an admin, so org-wide views stay closed.
 */
final class CallerAuth(verifier: Option[JwtVerifier]):
  import CallerAuth.*

  /** Rejects the request with 401 unless the caller is authenticated. */
  val caller: Directive1[Caller] =
    (optionalHeaderValueByName(UserIdHeader) & optionalHeaderValueByName("Authorization")).tflatMap {
      case (headerUserId, authorization) =>
        val forwardedId = headerUserId.map(_.trim).filter(_.nonEmpty)
        val resolved = verifier match
          case Some(v) =>
            bearerToken(authorization).flatMap(v.verify).filter(t => forwardedId.forall(_ == t.subject)).map { t =>
              Caller(t.subject, t.roles, authorization)
            }
          case None =>
            forwardedId.map(Caller(_, Set.empty, authorization))
        resolved match
          case Some(c) => provide(c)
          case None    => unauthorized.toDirective[Tuple1[Caller]]
    }

  /** Caller with an admin role; others get 403. */
  val adminCaller: Directive1[Caller] =
    caller.tflatMap { case Tuple1(c) =>
      if c.isAdmin then provide(c) else forbidden("Admin role required").toDirective[Tuple1[Caller]]
    }

object CallerAuth:
  val UserIdHeader = "X-User-ID"
  val AdminRoles: Set[String] = Set("ADMIN", "OWNER")

  def apply(jwtSecret: Option[String]): CallerAuth =
    new CallerAuth(jwtSecret.map(_.trim).filter(_.nonEmpty).map(JwtVerifier(_)))

  def bearerToken(authorization: Option[String]): Option[String] =
    authorization.map(_.trim.split("\\s+", 2)).collect {
      case Array(scheme, token) if scheme.equalsIgnoreCase("bearer") && token.nonEmpty => token
    }

  def authorize(allowed: Boolean): Directive0 =
    if allowed then pass else forbidden("Access denied").toDirective[Unit]

  private def unauthorized: StandardRoute =
    complete(StatusCodes.Unauthorized, JsObject("error" -> JsString("Authentication required")))

  def forbidden(message: String): StandardRoute =
    complete(StatusCodes.Forbidden, JsObject("error" -> JsString(message)))
