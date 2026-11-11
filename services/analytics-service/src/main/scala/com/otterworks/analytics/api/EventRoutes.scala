package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.Route
import com.otterworks.analytics.model.AnalyticsEventJsonProtocol.{*, given}
import com.otterworks.analytics.model.EventType
import com.otterworks.analytics.service.AnalyticsService
import org.slf4j.LoggerFactory

/**
 * Routes for event ingestion: POST /api/v1/analytics/events
 *
 * Events are bound to the verified caller: `userId` must match the access
 * token's subject. Internal producers publish to SQS instead.
 */
class EventRoutes(analyticsService: AnalyticsService, auth: AuthDirectives):

  import EventRoutes.*

  private val logger = LoggerFactory.getLogger(getClass)

  val routes: Route = pathPrefix("api" / "v1" / "analytics") {
    path("events") {
      (post & auth.authenticated) { user =>
        entity(as[TrackEventRequest]) { request =>
          val metadata = request.metadata.getOrElse(Map.empty)
          authorize(request.userId == user.userId) {
            validate(EventType.All.contains(request.eventType), s"unsupported eventType: ${request.eventType}") {
              validate(withinLimits(request, metadata), "event fields or metadata exceed size limits") {
                onSuccess(
                  analyticsService.trackEvent(
                    request.eventType,
                    user.userId,
                    request.resourceId,
                    request.resourceType,
                    metadata
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
  }

object EventRoutes:
  // Match analytics_events.resource_id VARCHAR(128) / resource_type VARCHAR(64).
  val MaxResourceIdLength = 128
  val MaxResourceTypeLength = 64
  val MaxMetadataEntries = 32
  val MaxMetadataKeyLength = 64
  val MaxMetadataValueLength = 1024

  private def withinLimits(request: TrackEventRequest, metadata: Map[String, String]): Boolean =
    request.resourceId.length <= MaxResourceIdLength &&
      request.resourceType.length <= MaxResourceTypeLength &&
      metadata.size <= MaxMetadataEntries &&
      metadata.forall((k, v) => k.length <= MaxMetadataKeyLength && v.length <= MaxMetadataValueLength)
