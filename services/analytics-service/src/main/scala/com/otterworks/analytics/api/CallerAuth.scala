package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.{Directive0, Directive1, StandardRoute}
import spray.json.{JsObject, JsString}

/**
 * Identity of the caller as asserted by the API gateway. The gateway strips any
 * client-supplied X-User-ID / X-User-Roles and sets them from the validated JWT
 * (`sub` and `roles` claims), so they are the only trusted source of identity.
 */
final case class Caller(userId: String, roles: Set[String]):
  def isAdmin: Boolean = roles.exists(CallerAuth.AdminRoles.contains)
  def canAccessUser(otherUserId: String): Boolean = isAdmin || otherUserId == userId

object CallerAuth:
  val UserIdHeader = "X-User-ID"
  val RolesHeader = "X-User-Roles"
  val AdminRoles: Set[String] = Set("ADMIN", "OWNER")

  def parseRoles(header: Option[String]): Set[String] =
    header.toList
      .flatMap(_.split(','))
      .map(_.trim.toUpperCase)
      .filter(_.nonEmpty)
      .toSet

  /** Rejects the request with 401 unless the gateway forwarded a caller identity. */
  val caller: Directive1[Caller] =
    (optionalHeaderValueByName(UserIdHeader) & optionalHeaderValueByName(RolesHeader)).tflatMap {
      case (userId, roles) =>
        userId.map(_.trim).filter(_.nonEmpty) match
          case Some(id) => provide(Caller(id, parseRoles(roles)))
          case None     => unauthorized.toDirective[Tuple1[Caller]]
    }

  /** Caller with an admin role; others get 403. */
  val adminCaller: Directive1[Caller] =
    caller.tflatMap { case Tuple1(c) =>
      if c.isAdmin then provide(c) else forbidden("Admin role required").toDirective[Tuple1[Caller]]
    }

  def authorize(allowed: Boolean): Directive0 =
    if allowed then pass else forbidden("Access denied").toDirective[Unit]

  private def unauthorized: StandardRoute =
    complete(StatusCodes.Unauthorized, JsObject("error" -> JsString("Authentication required")))

  def forbidden(message: String): StandardRoute =
    complete(StatusCodes.Forbidden, JsObject("error" -> JsString(message)))
