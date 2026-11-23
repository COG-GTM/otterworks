package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.StatusCodes
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.Route
import com.otterworks.analytics.model.*
import com.otterworks.analytics.model.MarketJsonProtocol.{*, given}
import com.otterworks.analytics.repository.MarketRepository
import com.otterworks.analytics.service.MarginService
import org.slf4j.LoggerFactory
import spray.json.*

/**
 * Market data routes:
 *   GET  /api/v1/analytics/market/series
 *   GET  /api/v1/analytics/market/prices?series_code=&from=&to=
 *   GET  /api/v1/analytics/market/status
 *   POST /api/v1/analytics/market/observations   (manual Trading Economics pulls)
 *
 * The API gateway validates the bearer token on every route. Reads are open to
 * any signed-in caller; posting observations overwrites prices and recomputes
 * tenant-wide margins, so it additionally requires an operator role
 * (ADMIN/OWNER, forwarded by the gateway as X-User-Roles).
 */
class MarketIngestRoutes(marginService: MarginService, repo: MarketRepository):

  private val logger = LoggerFactory.getLogger(getClass)

  val routes: Route = pathPrefix("api" / "v1" / "analytics" / "market") {
    concat(
      path("series") {
        get {
          onSuccess(repo.listSeries()) { series =>
            complete(JsObject("series" -> series.toList.toJson))
          }
        }
      },
      path("prices") {
        get {
          parameters("series_code", "from".optional, "to".optional) { (seriesCode, from, to) =>
            onSuccess(repo.listPrices(seriesCode, from, to)) { prices =>
              complete(JsObject("prices" -> prices.toList.toJson))
            }
          }
        }
      },
      path("status") {
        get {
          onSuccess(repo.marketStatus()) { status =>
            complete(status)
          }
        }
      },
      path("observations") {
        post {
          CallerAuth.adminOnly { caller =>
            entity(as[ObservationsRequest]) { request =>
              onSuccess(marginService.ingest(request)) {
                case Right(response) =>
                  logger.info("User {} ingested {} market observations", caller.userId, response.accepted)
                  complete(response)
                case Left(rejected) =>
                  logger.info("Rejected all {} market observations", rejected.size)
                  complete(
                    StatusCodes.BadRequest,
                    ObservationsResponse(accepted = 0, rejected = rejected, recomputedSkus = 0, runId = 0L)
                  )
              }
            }
          }
        }
      },
    )
  }
