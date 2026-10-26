package com.otterworks.notification.routes

import com.otterworks.notification.auth.CALLER_AUTH
import com.otterworks.notification.auth.callerId
import com.otterworks.notification.model.NotificationPreferenceRequest
import com.otterworks.notification.model.PaginatedResponse
import com.otterworks.notification.model.UnreadCountResponse
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.Application
import io.ktor.server.application.call
import io.ktor.server.auth.authenticate
import io.ktor.server.request.receive
import io.ktor.server.response.respond
import io.ktor.server.response.respondText
import io.ktor.server.routing.delete
import io.ktor.server.routing.get
import io.ktor.server.routing.Route
import io.ktor.server.routing.put
import io.ktor.server.routing.route
import io.ktor.server.routing.routing
import io.ktor.server.websocket.DefaultWebSocketServerSession
import io.ktor.server.websocket.webSocket
import io.ktor.websocket.CloseReason
import io.ktor.websocket.Frame
import io.ktor.websocket.close
import io.ktor.websocket.readText
import io.micrometer.prometheus.PrometheusMeterRegistry
import kotlinx.serialization.Serializable
import org.koin.ktor.ext.inject

@Serializable
data class HealthResponse(val status: String, val service: String)

@Serializable
data class ErrorResponse(val error: String)

@Serializable
data class MarkAllReadResponse(val markedCount: Int)

fun Application.configureRouting(prometheusRegistry: PrometheusMeterRegistry) {
    val notificationService by inject<NotificationService>()
    val webSocketManager by inject<WebSocketManager>()

    routing {
        get("/health") {
            call.respond(HealthResponse(status = "healthy", service = "notification-service"))
        }

        get("/metrics") {
            call.respondText(
                prometheusRegistry.scrape(),
                contentType = io.ktor.http.ContentType.Text.Plain,
            )
        }

        notificationApiRoutes(notificationService, webSocketManager)
    }
}

/**
 * Every caller-scoped route sits behind [CALLER_AUTH]: the user ID comes only from the verified
 * bearer token, never from `X-User-ID`, a `user_id` query parameter, the request body or the path,
 * so reaching the service without the gateway does not let a caller pick who they are.
 */
fun Route.notificationApiRoutes(
    notificationService: NotificationService,
    webSocketManager: WebSocketManager,
) {
    // A notification that belongs to someone else is reported as missing, not forbidden,
    // so IDs cannot be probed for existence.
    suspend fun ownedNotification(id: String, userId: String) =
        notificationService.getNotificationById(id)?.takeIf { it.userId == userId }

    authenticate(CALLER_AUTH) {
        route("/api/v1/notifications") {
            get {
                val userId = call.callerId
                val page = call.request.queryParameters["page"]?.toIntOrNull() ?: 1
                val pageSize = call.request.queryParameters["page_size"]?.toIntOrNull() ?: 20

                val (notifications, total) = notificationService.getNotifications(userId, page, pageSize)

                call.respond(
                    PaginatedResponse(
                        data = notifications,
                        total = total,
                        page = page,
                        pageSize = pageSize,
                        hasMore = (page * pageSize) < total,
                    )
                )
            }

            get("/unread-count") {
                val userId = call.callerId
                val count = notificationService.getUnreadCount(userId)
                call.respond(UnreadCountResponse(userId = userId, unreadCount = count))
            }

            get("/{id}") {
                val id = call.parameters["id"] ?: return@get call.respond(
                    HttpStatusCode.BadRequest,
                    ErrorResponse("Notification ID is required"),
                )

                val notification = ownedNotification(id, call.callerId)
                if (notification != null) {
                    call.respond(notification)
                } else {
                    call.respond(HttpStatusCode.NotFound, ErrorResponse("Notification not found"))
                }
            }

            put("/{id}/read") {
                val id = call.parameters["id"] ?: return@put call.respond(
                    HttpStatusCode.BadRequest,
                    ErrorResponse("Notification ID is required"),
                )

                val success = ownedNotification(id, call.callerId) != null && notificationService.markAsRead(id)
                if (success) {
                    call.respond(HttpStatusCode.NoContent)
                } else {
                    call.respond(HttpStatusCode.NotFound, ErrorResponse("Notification not found"))
                }
            }

            put("/read-all") {
                val count = notificationService.markAllAsRead(call.callerId)
                call.respond(MarkAllReadResponse(markedCount = count))
            }

            delete("/{id}") {
                val id = call.parameters["id"] ?: return@delete call.respond(
                    HttpStatusCode.BadRequest,
                    ErrorResponse("Notification ID is required"),
                )

                val success = ownedNotification(id, call.callerId) != null && notificationService.deleteNotification(id)
                if (success) {
                    call.respond(HttpStatusCode.NoContent)
                } else {
                    call.respond(HttpStatusCode.NotFound, ErrorResponse("Notification not found"))
                }
            }
        }

        route("/api/v1/preferences") {
            get {
                val preferences = notificationService.getPreferences(call.callerId)
                call.respond(preferences)
            }

            put {
                val userId = call.callerId
                val request = call.receive<NotificationPreferenceRequest>()
                if (request.userId != null && request.userId != userId) {
                    call.respond(HttpStatusCode.Forbidden, ErrorResponse("cannot update another user's preferences"))
                    return@put
                }
                notificationService.updatePreferences(
                    userId = userId,
                    eventType = request.eventType,
                    channels = request.channels,
                )
                call.respond(HttpStatusCode.NoContent)
            }
        }

        webSocket("/ws/notifications") {
            relayNotifications(call.callerId, webSocketManager)
        }

        // Kept for existing clients; the path must name the authenticated caller.
        webSocket("/ws/notifications/{userId}") {
            val userId = call.callerId
            if (call.parameters["userId"] != userId) {
                close(CloseReason(CloseReason.Codes.VIOLATED_POLICY, "userId does not match the authenticated caller"))
                return@webSocket
            }
            relayNotifications(userId, webSocketManager)
        }
    }
}

private suspend fun DefaultWebSocketServerSession.relayNotifications(
    userId: String,
    webSocketManager: WebSocketManager,
) {
    webSocketManager.addConnection(userId, this)

    try {
        for (frame in incoming) {
            when (frame) {
                is Frame.Text -> {
                    val text = frame.readText()
                    // Handle ping/pong or client messages if needed
                    if (text == "ping") {
                        send(Frame.Text("pong"))
                    }
                }
                is Frame.Close -> break
                else -> { /* ignore other frame types */ }
            }
        }
    } finally {
        webSocketManager.removeConnection(userId, this)
    }
}
