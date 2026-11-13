package com.otterworks.notification.routes

import com.otterworks.notification.model.NotificationPreferenceRequest
import com.otterworks.notification.model.PaginatedResponse
import com.otterworks.notification.model.UnreadCountResponse
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.Application
import io.ktor.server.application.ApplicationCall
import io.ktor.server.application.call
import io.ktor.server.request.receive
import io.ktor.server.response.respond
import io.ktor.server.response.respondText
import io.ktor.server.routing.Route
import io.ktor.server.routing.delete
import io.ktor.server.routing.get
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

private const val USER_ID_HEADER = "X-User-ID"
private const val USER_ID_QUERY_PARAM = "user_id"
private const val USER_ID_REQUIRED = "user_id is required (via $USER_ID_HEADER header or query parameter)"
private const val NOTIFICATION_ID_REQUIRED = "Notification ID is required"
private const val NOTIFICATION_NOT_FOUND = "Notification not found"

fun Application.configureRouting(prometheusRegistry: PrometheusMeterRegistry) {
    val notificationService by inject<NotificationService>()
    val webSocketManager by inject<WebSocketManager>()

    routing {
        healthRoutes(prometheusRegistry)
        notificationRoutes { notificationService }
        preferenceRoutes { notificationService }
        notificationWebSocket { webSocketManager }
    }
}

private fun Route.healthRoutes(prometheusRegistry: PrometheusMeterRegistry) {
    get("/health") {
        call.respond(HealthResponse(status = "healthy", service = "notification-service"))
    }

    get("/metrics") {
        call.respondText(
            prometheusRegistry.scrape(),
            contentType = io.ktor.http.ContentType.Text.Plain,
        )
    }
}

private fun Route.notificationRoutes(service: () -> NotificationService) {
    route("/api/v1/notifications") {
        get {
            call.withUserId { userId ->
                val page = call.request.queryParameters["page"]?.toIntOrNull() ?: 1
                val pageSize = call.request.queryParameters["page_size"]?.toIntOrNull() ?: 20
                val (notifications, total) = service().getNotifications(userId, page, pageSize)
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
        }

        get("/unread-count") {
            call.withUserId { userId ->
                call.respond(UnreadCountResponse(userId = userId, unreadCount = service().getUnreadCount(userId)))
            }
        }

        get("/{id}") {
            call.withNotificationId { id ->
                val notification = service().getNotificationById(id)
                if (notification != null) call.respond(notification) else call.respondNotificationNotFound()
            }
        }

        put("/{id}/read") {
            call.withNotificationId { id -> call.respondNoContentOrNotFound(service().markAsRead(id)) }
        }

        put("/read-all") {
            call.withUserId { userId ->
                call.respond(MarkAllReadResponse(markedCount = service().markAllAsRead(userId)))
            }
        }

        delete("/{id}") {
            call.withNotificationId { id -> call.respondNoContentOrNotFound(service().deleteNotification(id)) }
        }
    }
}

private fun Route.preferenceRoutes(service: () -> NotificationService) {
    route("/api/v1/preferences") {
        get {
            call.withUserId { userId -> call.respond(service().getPreferences(userId)) }
        }

        put {
            val request = call.receive<NotificationPreferenceRequest>()
            service().updatePreferences(
                userId = request.userId,
                eventType = request.eventType,
                channels = request.channels,
            )
            call.respond(HttpStatusCode.NoContent)
        }
    }
}

private fun Route.notificationWebSocket(webSocketManager: () -> WebSocketManager) {
    webSocket("/ws/notifications/{userId}") {
        val userId = call.parameters["userId"]
        if (userId.isNullOrBlank()) {
            close(CloseReason(CloseReason.Codes.VIOLATED_POLICY, "userId is required"))
            return@webSocket
        }

        webSocketManager().addConnection(userId, this)
        try {
            handleClientFrames()
        } finally {
            webSocketManager().removeConnection(userId, this)
        }
    }
}

private suspend fun DefaultWebSocketServerSession.handleClientFrames() {
    for (frame in incoming) {
        if (frame is Frame.Close) break
        if (frame is Frame.Text && frame.readText() == "ping") {
            send(Frame.Text("pong"))
        }
    }
}

private suspend inline fun ApplicationCall.withUserId(block: (String) -> Unit) {
    val userId = request.headers[USER_ID_HEADER] ?: request.queryParameters[USER_ID_QUERY_PARAM]
    if (userId.isNullOrBlank()) {
        respond(HttpStatusCode.BadRequest, ErrorResponse(USER_ID_REQUIRED))
    } else {
        block(userId)
    }
}

private suspend inline fun ApplicationCall.withNotificationId(block: (String) -> Unit) {
    val id = parameters["id"]
    if (id == null) {
        respond(HttpStatusCode.BadRequest, ErrorResponse(NOTIFICATION_ID_REQUIRED))
    } else {
        block(id)
    }
}

private suspend fun ApplicationCall.respondNotificationNotFound() {
    respond(HttpStatusCode.NotFound, ErrorResponse(NOTIFICATION_NOT_FOUND))
}

private suspend fun ApplicationCall.respondNoContentOrNotFound(found: Boolean) {
    if (found) respond(HttpStatusCode.NoContent) else respondNotificationNotFound()
}
