package com.otterworks.analytics.api

import akka.http.scaladsl.model.{ContentTypes, HttpEntity, HttpResponse, StatusCode, StatusCodes}
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.Route
import spray.json.{JsObject, JsString}

/** The caller of an analytics query, as identified by the API gateway. */
final case class Caller(userId: String, roles: Set[String]):
  def isAdmin: Boolean = roles.exists(CallerAuth.AdminRoles.contains)
  def canViewUser(targetUserId: String): Boolean = isAdmin || targetUserId == userId

/**
 * Resolves the caller from the identity headers the API gateway derives from the
 * validated JWT (`X-User-ID` from the subject, `X-User-Roles` from the `roles`
 * claim). The gateway strips client-supplied copies of both headers.
 */
object CallerAuth:
  val UserIdHeader = "X-User-ID"
  val RolesHeader = "X-User-Roles"
  val AdminRoles: Set[String] = Set("ADMIN", "OWNER")

  def parseRoles(raw: Option[String]): Set[String] =
    raw.toList.flatMap(_.split(',')).map(_.trim.toUpperCase).filter(_.nonEmpty).toSet

  /** Runs `inner` with the caller, or answers 401 when no identity was forwarded. */
  def authenticated(inner: Caller => Route): Route =
    optionalHeaderValueByName(UserIdHeader) { rawUserId =>
      optionalHeaderValueByName(RolesHeader) { rawRoles =>
        rawUserId.map(_.trim).filter(_.nonEmpty) match
          case Some(userId) => inner(Caller(userId, parseRoles(rawRoles)))
          case None         => error(StatusCodes.Unauthorized, "Authentication required")
      }
    }

  /** Runs `inner` for callers with an admin role; others get 403. */
  def adminOnly(inner: Caller => Route): Route =
    authenticated { caller =>
      if caller.isAdmin then inner(caller) else error(StatusCodes.Forbidden, "Admin role required")
    }

  def forbidden: Route = error(StatusCodes.Forbidden, "Access denied")

  private def error(status: StatusCode, message: String): Route =
    complete(
      HttpResponse(
        status,
        entity = HttpEntity(ContentTypes.`application/json`, JsObject("error" -> JsString(message)).compactPrint)
      )
    )
