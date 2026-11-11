package com.otterworks.analytics.api

import akka.http.scaladsl.marshallers.sprayjson.SprayJsonSupport.*
import akka.http.scaladsl.model.{ContentTypes, HttpEntity, StatusCodes}
import akka.http.scaladsl.server.Directives.*
import akka.http.scaladsl.server.Route
import com.otterworks.analytics.model.DashboardJsonProtocol.{*, given}
import com.otterworks.analytics.api.CallerDirectives.{allowIf, caller}
import com.otterworks.analytics.service.{AnalyticsService, DocumentAccess}
import spray.json.*

import java.time.Instant
import scala.concurrent.Future

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
 * Every route requires the gateway-asserted caller (X-User-ID). Per-user and
 * per-document views are limited to the caller's own data; cross-user views
 * (dashboard, top-content, active-users, export, storage without user_id)
 * require an admin role.
 */
class AnalyticsRoutes(analyticsService: AnalyticsService, documentAccess: DocumentAccess):

  val routes: Route = pathPrefix("api" / "v1" / "analytics") {
    concat(
      // Dashboard Summary
      path("dashboard") {
        get {
          (caller & parameters("period".withDefault("7d"))) { (who, period) =>
            allowIf(who.isAdmin) {
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
            caller { who =>
              allowIf(who.canActAs(userId)) {
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
            (caller & optionalHeaderValueByName("Authorization")) { (who, authorization) =>
              val access =
                if who.isAdmin then Future.successful(true)
                else documentAccess.canView(documentId, who.userId, authorization)
              onSuccess(access) { allowed =>
                allowIf(allowed) {
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
          (caller & parameters(
            "type".withDefault("documents"),
            "period".withDefault("7d"),
            "limit".as[Int].withDefault(10)
          )) { (who, contentType, period, limit) =>
            allowIf(who.isAdmin) {
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
          (caller & parameters("period".withDefault("daily"))) { (who, period) =>
            allowIf(who.isAdmin) {
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
          (caller & parameters("user_id".optional)) { (who, userId) =>
            allowIf(userId.fold(who.isAdmin)(who.canActAs)) {
              onSuccess(analyticsService.getStorageUsage(userId)) { response =>
                complete(response)
              }
            }
          }
        }
      },

      // Export Report
      path("export") {
        get {
          (caller & parameters(
            "format".withDefault("json"),
            "period".withDefault("7d")
          )) { (who, format, period) =>
            allowIf(who.isAdmin) {
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
