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
 * Analytics query routes. Callers are identified by the gateway's X-User-ID /
 * X-User-Roles headers (see [[CallerAuth]]): per-user activity and storage are
 * limited to the caller's own data unless the caller is an admin, and the
 * cross-user aggregates (dashboard, top-content, active-users, export) are
 * admin-only.
 *
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
          CallerAuth.adminOnly { _ =>
            parameters("period".withDefault("7d")) { period =>
              onSuccess(analyticsService.getDashboardSummary(period)) { summary =>
                complete(summary)
              }
            }
          }
        }
      },

      // User Activity
      pathPrefix("users") {
        path(Segment / "activity") { userId =>
          get {
            CallerAuth.authenticated { caller =>
              if !caller.canViewUser(userId) then CallerAuth.forbidden
              else
                onSuccess(analyticsService.getUserActivity(userId)) { activity =>
                  complete(activity)
                }
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
          CallerAuth.adminOnly { _ =>
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
        }
      },

      // Active Users
      path("active-users") {
        get {
          CallerAuth.adminOnly { _ =>
            parameters("period".withDefault("daily")) { period =>
              onSuccess(analyticsService.getActiveUsers(period)) { response =>
                complete(response)
              }
            }
          }
        }
      },

      // Storage Usage
      path("storage") {
        get {
          CallerAuth.authenticated { caller =>
            parameters("user_id".optional) { requested =>
              // Non-admins only ever see their own usage; the global view is admin-only.
              val target = if caller.isAdmin then requested else requested.orElse(Some(caller.userId))
              if target.exists(id => !caller.canViewUser(id)) then CallerAuth.forbidden
              else
                onSuccess(analyticsService.getStorageUsage(target)) { response =>
                  complete(response)
                }
            }
          }
        }
      },

      // Export Report
      path("export") {
        get {
          CallerAuth.adminOnly { _ =>
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
        }
      },
    )
  }

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
