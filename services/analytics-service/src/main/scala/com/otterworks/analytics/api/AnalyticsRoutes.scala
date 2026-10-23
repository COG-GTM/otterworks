package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.{ContentTypes, HttpEntity, StatusCodes}
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.Route
import com.otterworks.analytics.model.DashboardJsonProtocol.{*, given}
import com.otterworks.analytics.service.AnalyticsService
import spray.json.*

import java.time.Instant

/**
 * Analytics query routes:
 *   GET /api/v1/analytics/dashboard
 *   GET /api/v1/analytics/users/{id}/activity
 *   GET /api/v1/analytics/documents/{id}/stats
 *   GET /api/v1/analytics/top-content
 *   GET /api/v1/analytics/active-users
 *   GET /api/v1/analytics/storage
 *   GET /api/v1/analytics/export
 */
class AnalyticsRoutes(analyticsService: AnalyticsService):

  val routes: Route = pathPrefix("api" / "v1" / "analytics") {
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
            onSuccess(analyticsService.getTopContent(contentType, period, limit)) { response =>
              complete(response)
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
  }

  private[api] def buildCsvContent(data: List[Map[String, String]]): String =
    val headers = List("event_id", "event_type", "user_id", "resource_id", "resource_type", "timestamp")
    val rows = data.map { row =>
      headers.map(h => CsvCell.text(row.getOrElse(h, ""))).mkString(",")
    }
    (headers.mkString(",") :: rows).mkString("\n") + "\n"
