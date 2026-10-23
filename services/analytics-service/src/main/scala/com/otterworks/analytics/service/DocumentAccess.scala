package com.otterworks.analytics.service

import akka.actor.ClassicActorSystemProvider
import akka.http.scaladsl.Http
import akka.http.scaladsl.model.headers.RawHeader
import akka.http.scaladsl.model.{HttpRequest, StatusCodes}
import akka.pattern.after
import com.otterworks.analytics.api.{Caller, CallerAuth}
import org.slf4j.LoggerFactory

import scala.concurrent.duration.FiniteDuration
import scala.concurrent.{ExecutionContext, Future, TimeoutException}
import scala.util.control.NonFatal

/** Decides whether a caller may see analytics for a document. */
trait DocumentAccess:
  def canView(caller: Caller, documentId: String): Future[Boolean]

object DocumentAccess:
  private val UuidPattern = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$".r

  def isDocumentId(value: String): Boolean = UuidPattern.matches(value)

/**
 * Delegates the ownership/share decision to document-service, which owns the
 * documents table: the caller may see a document's analytics only if
 * `GET /api/v1/documents/{id}` succeeds for them. The caller's own bearer token
 * is forwarded so document-service verifies it as usual. Fails closed on any error.
 */
final class DocumentServiceAccess(baseUrl: String, timeout: FiniteDuration)(using system: ClassicActorSystemProvider)
    extends DocumentAccess:

  private val logger = LoggerFactory.getLogger(getClass)
  private given ec: ExecutionContext = system.classicSystem.dispatcher
  private val base = baseUrl.stripSuffix("/")

  def canView(caller: Caller, documentId: String): Future[Boolean] =
    if !DocumentAccess.isDocumentId(documentId) then Future.successful(false)
    else
      val request = HttpRequest(uri = s"$base/api/v1/documents/$documentId")
        .withHeaders(
          RawHeader(CallerAuth.UserIdHeader, caller.userId) ::
            caller.authorization.map(RawHeader("Authorization", _)).toList
        )
      val lookup = Http().singleRequest(request).flatMap { response =>
        response.discardEntityBytes().future.map(_ => response.status == StatusCodes.OK)
      }
      val deadline = after(timeout, system.classicSystem.scheduler)(
        Future.failed[Boolean](new TimeoutException(s"document-service did not answer within $timeout")))
      Future.firstCompletedOf(Seq(lookup, deadline)).recover { case NonFatal(ex) =>
        logger.warn("Document access check failed for document={}: {}", documentId, ex.getMessage)
        false
      }
