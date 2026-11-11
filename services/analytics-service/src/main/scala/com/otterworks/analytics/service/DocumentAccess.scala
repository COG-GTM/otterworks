package com.otterworks.analytics.service

import akka.actor.ClassicActorSystemProvider
import akka.http.scaladsl.Http
import akka.http.scaladsl.model.headers.RawHeader
import akka.http.scaladsl.model.{HttpRequest, StatusCodes, Uri}
import org.slf4j.LoggerFactory

import scala.concurrent.{ExecutionContext, Future}
import scala.util.control.NonFatal

/** Decides whether a user may see analytics for a document. */
trait DocumentAccess:
  def canView(documentId: String, userId: String, authorization: Option[String]): Future[Boolean]

/**
 * Delegates the ownership decision to document-service, which owns the
 * document rows: the caller may see a document's stats only if
 * document-service would return that document to them. The caller's bearer
 * token is forwarded because document-service authenticates from the JWT.
 * Fails closed.
 */
class HttpDocumentAccess(baseUrl: String)(using system: ClassicActorSystemProvider, ec: ExecutionContext)
    extends DocumentAccess:

  private val logger = LoggerFactory.getLogger(getClass)
  private val base = Uri(baseUrl.stripSuffix("/"))

  def canView(documentId: String, userId: String, authorization: Option[String]): Future[Boolean] =
    val request = HttpRequest(
      uri = base.withPath(base.path ++ Uri.Path("/api/v1/documents") / documentId),
      headers = RawHeader("X-User-ID", userId) :: authorization.map(RawHeader("Authorization", _)).toList
    )
    Http()
      .singleRequest(request)
      .map { response =>
        response.discardEntityBytes()
        response.status == StatusCodes.OK
      }
      .recover { case NonFatal(ex) =>
        logger.warn("document-service access check failed for document={}: {}", documentId, ex.getMessage)
        false
      }
