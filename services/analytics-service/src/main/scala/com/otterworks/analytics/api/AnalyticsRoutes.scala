package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.{ContentTypes, HttpEntity}
import akka.http.scaladsl.server.Directives.{authorize as _, *}
import akka.http.scaladsl.server.Route
import com.otterworks.analytics.api.CallerAuth.{adminCaller, authorize, caller}
import com.otterworks.analytics.model.DashboardJsonProtocol.{*, given}
import com.otterworks.analytics.service.{AnalyticsService, DocumentAccess}
import spray.json.*

import scala.concurrent.Future

/**
 * Analytics query routes. Every route requires the gateway-forwarded caller
 * identity (see [[CallerAuth]]):
 *   GET /api/v1/analytics/dashboard            admin
 *   GET /api/v1/analytics/users/{id}/activity  the user themself or admin
 *   GET /api/v1/analytics/documents/{id}/stats document reader (per document-service) or admin
 *   GET /api/v1/analytics/top-content          admin
 *   GET /api/v1/analytics/active-users         admin
 *   GET /api/v1/analytics/storage              own user_id, or admin (required without user_id)
 *   GET /api/v1/analytics/export               admin
 */
class AnalyticsRoutes(analyticsService: AnalyticsService, documentAccess: DocumentAccess):

  val routes: Route = pathPrefix("api" / "v1" / "analytics") {
    concat(
      // Dashboard Summary
      path("dashboard") {
        get {
          adminCaller { _ =>
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
            caller { c =>
              authorize(c.canAccessUser(userId)) {
                onSuccess(analyticsService.getUserActivity(userId)) { activity =>
                  complete(activity)
                }
              }
            }
          }
        }
      },

      // Document Analytics
      pathPrefix("documents") {
        path(Segment / "stats") { documentId =>
          get {
            caller { c =>
              val allowed =
                if c.isAdmin then Future.successful(true) else documentAccess.canView(c, documentId)
              onSuccess(allowed) { ok =>
                authorize(ok) {
                  onSuccess(analyticsService.getDocumentStats(documentId)) { stats =>
                    complete(stats)
                  }
                }
              }
            }
          }
        }
      },

      // Top Content
      path("top-content") {
        get {
          adminCaller { _ =>
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
          adminCaller { _ =>
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
          caller { c =>
            parameters("user_id".optional) { userId =>
              authorize(c.isAdmin || userId.contains(c.userId)) {
                onSuccess(analyticsService.getStorageUsage(userId)) { response =>
                  complete(response)
                }
              }
            }
          }
        }
      },

      // Export Report
      path("export") {
        get {
          adminCaller { _ =>
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
