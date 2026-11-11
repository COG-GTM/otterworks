package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.{Directive0, Directive1}
import spray.json.{JsObject, JsString}

/** The authenticated caller, as asserted by the API gateway from a validated JWT. */
final case class Caller(userId: String, roles: Set[String]):
  def isAdmin: Boolean = roles.exists(CallerDirectives.AdminRoles.contains)
  def canActAs(otherUserId: String): Boolean = isAdmin || otherUserId == userId

/**
 * Identity directives for routes behind the API gateway. The gateway strips any
 * client-supplied X-User-ID / X-User-Roles and re-derives them from the JWT.
 */
object CallerDirectives:
  val UserIdHeader = "X-User-ID"
  val RolesHeader = "X-User-Roles"

  // Mirrors admin-service's ADMIN_ROLES (auth-service roles are upper-case enum names).
  val AdminRoles: Set[String] = Set("admin", "super_admin", "owner")

  val caller: Directive1[Caller] =
    optionalHeaderValueByName(UserIdHeader).flatMap {
      case Some(id) if id.trim.nonEmpty =>
        optionalHeaderValueByName(RolesHeader).map(roles => Caller(id.trim, parseRoles(roles)))
      case _ =>
        complete(StatusCodes.Unauthorized, JsObject("error" -> JsString("authentication required")))
    }

  def allowIf(allowed: Boolean): Directive0 =
    if allowed then pass
    else complete(StatusCodes.Forbidden, JsObject("error" -> JsString("access denied")))

  private def parseRoles(header: Option[String]): Set[String] =
    header.toList
      .flatMap(_.split(","))
      .map(_.trim.toLowerCase)
      .filter(_.nonEmpty)
      .toSet
