package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.headers.`Retry-After`
import akka.http.scaladsl.model.{ContentTypes, HttpEntity, HttpResponse, StatusCodes}
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.{Directive, Directive0, Route, RouteResult}
import com.otterworks.analytics.model.DashboardJsonProtocol.{*, given}
import com.otterworks.analytics.repository.MetricsAggregator
import com.otterworks.analytics.service.AnalyticsService
import spray.json.*

import java.time.Instant
import java.util.concurrent.atomic.AtomicInteger
import scala.concurrent.Future
import scala.util.control.NonFatal

/**
 * Analytics query routes:
 *   GET /api/v1/analytics/dashboard
 *   GET /api/v1/analytics/users/{id}/activity
 *   GET /api/v1/analytics/documents/{id}/stats
 *   GET /api/v1/analytics/top-content
 *   GET /api/v1/analytics/active-users
 *   GET /api/v1/analytics/storage
 *   GET /api/v1/analytics/export
 *
 * Every query is aggregation work, so at most `maxConcurrentQueries` run at
 * once; extra requests are shed with 503 + Retry-After instead of queueing.
 */
class AnalyticsRoutes(
    analyticsService: AnalyticsService,
    maxConcurrentQueries: Int = AnalyticsRoutes.DefaultMaxConcurrentQueries
):

  require(maxConcurrentQueries > 0, "maxConcurrentQueries must be positive")

  private val inFlight = new AtomicInteger(0)

  private val querySlot: Directive0 = Directive[Unit] { inner => ctx =>
    if inFlight.incrementAndGet() > maxConcurrentQueries then
      inFlight.decrementAndGet()
      ctx.complete(
        HttpResponse(
          StatusCodes.ServiceUnavailable,
          headers = List(`Retry-After`(1L)),
          entity = HttpEntity(ContentTypes.`application/json`, """{"error":"too many concurrent analytics queries"}""")
        )
      )
    else
      val result: Future[RouteResult] =
        try inner(())(ctx)
        catch case NonFatal(e) => Future.failed(e)
      result.andThen { case _ => inFlight.decrementAndGet() }(using ctx.executionContext)
  }

  val routes: Route = pathPrefix("api" / "v1" / "analytics") {
    (get & querySlot) { queryRoutes }
  }

  private def queryRoutes: Route =
    concat(
      // Dashboard Summary
      path("dashboard") {
        get {
          parameters("period".withDefault("7d")) { period =>
            onSuccess(analyticsService.getDashboardSummary(period)) { summary =>
              complete(summary)
            }
          }
        }
      },

      // User Activity
      pathPrefix("users") {
        path(Segment / "activity") { userId =>
          get {
            onSuccess(analyticsService.getUserActivity(userId)) { activity =>
              complete(activity)
            }
          }
        }
      },

      // Document Analytics
      pathPrefix("documents") {
        path(Segment / "stats") { documentId =>
          get {
            onSuccess(analyticsService.getDocumentStats(documentId)) { stats =>
              complete(stats)
            }
          }
        }
      },

      // Top Content
      path("top-content") {
        get {
          parameters(
            "type".withDefault("documents"),
            "period".withDefault("7d"),
            "limit".as[Int].withDefault(10)
          ) { (contentType, period, limit) =>
            validate(
              limit >= 1 && limit <= MetricsAggregator.Limits.MaxTopContent,
              s"limit must be between 1 and ${MetricsAggregator.Limits.MaxTopContent}"
            ) {
            onSuccess(analyticsService.getTopContent(contentType, period, limit)) { response =>
              complete(response)
            }
            }
          }
        }
      },

      // Active Users
      path("active-users") {
        get {
          parameters("period".withDefault("daily")) { period =>
            onSuccess(analyticsService.getActiveUsers(period)) { response =>
              complete(response)
            }
          }
        }
      },

      // Storage Usage
      path("storage") {
        get {
          parameters("user_id".optional) { userId =>
            onSuccess(analyticsService.getStorageUsage(userId)) { response =>
              complete(response)
            }
          }
        }
      },

      // Export Report
      path("export") {
        get {
          parameters(
            "format".withDefault("json"),
            "period".withDefault("7d")
          ) { (format, period) =>
            format match
              case "csv" =>
                onSuccess(analyticsService.exportReport("csv", period)) { report =>
                  val csvContent = buildCsvContent(report.data)
                  complete(HttpEntity(ContentTypes.`text/plain(UTF-8)`, csvContent))
                }
              case _ =>
                onSuccess(analyticsService.exportReport("json", period)) { report =>
                  complete(report)
                }
          }
        }
      },
    )

  private def buildCsvContent(data: List[Map[String, String]]): String =
    if data.isEmpty then "event_id,event_type,user_id,resource_id,resource_type,timestamp\n"
    else
      val headers = List("event_id", "event_type", "user_id", "resource_id", "resource_type", "timestamp")
      val headerLine = headers.mkString(",")
      val rows = data.map { row =>
        headers.map(h => escapeCsvField(row.getOrElse(h, ""))).mkString(",")
      }
      (headerLine :: rows).mkString("\n") + "\n"

  private def escapeCsvField(value: String): String =
    if value.contains(",") || value.contains("\"") || value.contains("\n") then
      "\"" + value.replace("\"", "\"\"") + "\""
    else value

object AnalyticsRoutes:
  val DefaultMaxConcurrentQueries: Int = 8
