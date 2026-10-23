package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.Route
import com.otterworks.analytics.model.AnalyticsEventJsonProtocol.{*, given}
import com.otterworks.analytics.model.TrackEventPolicy
import com.otterworks.analytics.service.AnalyticsService
import org.slf4j.LoggerFactory

/**
 * Routes for event ingestion: POST /api/v1/analytics/events
 *
 * The event is attributed to the caller the API gateway asserts in X-User-ID
 * (stripped from client requests and set from the validated JWT), never to a
 * body-supplied user id.
 */
class EventRoutes(analyticsService: AnalyticsService):

  private val logger = LoggerFactory.getLogger(getClass)

  val routes: Route = pathPrefix("api" / "v1" / "analytics") {
    path("events") {
      post {
        optionalHeaderValueByName(EventRoutes.UserIdHeader) { header =>
          header.map(_.trim).filter(_.nonEmpty) match
            case None =>
              complete(StatusCodes.Unauthorized, ErrorResponse("Authentication required"))
            case Some(callerId) =>
              withSizeLimit(TrackEventPolicy.MaxBodyBytes) {
                entity(as[TrackEventRequest]) { request =>
                  if request.userId.exists(_ != callerId) then
                    complete(StatusCodes.Forbidden, ErrorResponse("userId must match the authenticated caller"))
                  else
                    TrackEventPolicy.validate(request) match
                      case Left(error) =>
                        complete(StatusCodes.BadRequest, ErrorResponse(error))
                      case Right(_) =>
                        onSuccess(
                          analyticsService.trackEvent(
                            request.eventType,
                            callerId,
                            request.resourceId,
                            request.resourceType,
                            request.metadata.getOrElse(Map.empty)
                          )
                        ) { event =>
                          logger.info("Event tracked: {}", event.eventId)
                          complete(StatusCodes.Accepted, AcceptedResponse("accepted", event.eventId))
                        }
                }
              }
        }
      }
    }
  }

object EventRoutes:
  val UserIdHeader = "X-User-ID"
