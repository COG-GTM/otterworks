package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.Route
import com.otterworks.analytics.model.AnalyticsEventJsonProtocol.{*, given}
import com.otterworks.analytics.service.AnalyticsService
import org.slf4j.LoggerFactory

/**
 * Routes for event ingestion: POST /api/v1/analytics/events
 *
 * Request bodies and field sizes are bounded so a single write cannot store
 * arbitrarily large rows (the column widths mirror V1__create_analytics_tables).
 */
class EventRoutes(analyticsService: AnalyticsService):
  import EventRoutes.*

  private val logger = LoggerFactory.getLogger(getClass)

  val routes: Route = pathPrefix("api" / "v1" / "analytics") {
    path("events") {
      (post & withSizeLimit(MaxBodyBytes)) {
        entity(as[TrackEventRequest]) { request =>
          validate(isWithinLimits(request), "event fields exceed allowed sizes") {
          onSuccess(
            analyticsService.trackEvent(
              request.eventType,
              request.userId,
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

object EventRoutes:
  val MaxBodyBytes: Long = 16L * 1024
  val MaxMetadataEntries: Int = 32
  val MaxMetadataValueLength: Int = 1024

  private[api] def isWithinLimits(r: TrackEventRequest): Boolean =
    val metadata = r.metadata.getOrElse(Map.empty)
    r.eventType.nonEmpty && r.eventType.length <= 64 &&
    r.userId.nonEmpty && r.userId.length <= 128 &&
    r.resourceId.length <= 128 &&
    r.resourceType.length <= 64 &&
    metadata.size <= MaxMetadataEntries &&
    metadata.forall { case (k, v) => k.length <= 128 && v.length <= MaxMetadataValueLength }
