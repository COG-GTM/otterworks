package com.otterworks.notification.routes

import com.auth0.jwt.JWT
import com.auth0.jwt.algorithms.Algorithm
import com.auth0.jwt.exceptions.JWTVerificationException
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
import io.ktor.server.routing.delete
import io.ktor.server.routing.get
import io.ktor.server.routing.put
import io.ktor.server.routing.route
import io.ktor.server.routing.routing
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

/**
 * Resolves the authenticated caller for a request. Identity never comes from
 * client-chosen input (query parameters, request bodies, URL paths).
 *
 * With a JWT secret configured, the caller is the subject of a valid bearer
 * token signed with that secret, and a forwarded `X-User-ID` must agree with
 * it. Without one, the service falls back to trusting the `X-User-ID` header
 * the API gateway sets from the token it validated.
 */
class CallerIdentityResolver(jwtSecret: String?) {
    private val secret: ByteArray? = jwtSecret?.takeIf { it.isNotBlank() }?.toByteArray(Charsets.UTF_8)

    val verifiesTokens: Boolean get() = secret != null

    /**
     * @param allowQueryToken accept the token from the `access_token` query
     * parameter (browsers cannot set headers on a WebSocket handshake). Only
     * honored when tokens are verified.
     */
    fun resolve(call: ApplicationCall, allowQueryToken: Boolean = false): String? {
        val forwardedUserId = call.request.headers[USER_ID_HEADER]?.trim()?.takeIf { it.isNotEmpty() }
        if (secret == null) {
            return if (allowQueryToken) null else forwardedUserId
        }

        val token = bearerToken(call)
            ?: if (allowQueryToken) call.request.queryParameters["access_token"] else null
        val subject = token?.let { verify(it, secret) } ?: return null
        if (forwardedUserId != null && forwardedUserId != subject) return null
        return subject
    }

    private fun bearerToken(call: ApplicationCall): String? {
        val parts = call.request.headers["Authorization"]?.trim()?.split(" ", limit = 2) ?: return null
        if (parts.size != 2 || !parts[0].equals("bearer", ignoreCase = true)) return null
        return parts[1].trim().takeIf { it.isNotEmpty() }
    }

    private fun verify(token: String, secret: ByteArray): String? = try {
        val algorithm = when (JWT.decode(token).algorithm) {
            "HS256" -> Algorithm.HMAC256(secret)
            "HS384" -> Algorithm.HMAC384(secret)
            "HS512" -> Algorithm.HMAC512(secret)
            else -> null
        }
        algorithm?.let { JWT.require(it).build().verify(token) }
            ?.takeIf { it.getClaim("type").asString() != "refresh" }
            ?.let { jwt ->
                jwt.subject?.takeIf { it.isNotBlank() }
                    ?: jwt.getClaim("user_id").asString()?.takeIf { it.isNotBlank() }
            }
    } catch (_: JWTVerificationException) {
        null
    }

    companion object {
        const val USER_ID_HEADER = "X-User-ID"
    }
}

private suspend fun ApplicationCall.requireCaller(resolver: CallerIdentityResolver): String? {
    val userId = resolver.resolve(this)
    if (userId == null) {
        respond(HttpStatusCode.Unauthorized, ErrorResponse("authentication required"))
    }
    return userId
}

fun Application.configureRouting(prometheusRegistry: PrometheusMeterRegistry) {
    val notificationService by inject<NotificationService>()
    val webSocketManager by inject<WebSocketManager>()
    val callerIdentity by inject<CallerIdentityResolver>()

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

        route("/api/v1/notifications") {
            get {
                val userId = call.requireCaller(callerIdentity) ?: return@get

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
                val userId = call.requireCaller(callerIdentity) ?: return@get

                val count = notificationService.getUnreadCount(userId)
                call.respond(UnreadCountResponse(userId = userId, unreadCount = count))
            }

            get("/{id}") {
                val userId = call.requireCaller(callerIdentity) ?: return@get
                val id = call.parameters["id"] ?: return@get call.respond(
                    HttpStatusCode.BadRequest,
                    ErrorResponse("Notification ID is required"),
                )

                val notification = notificationService.getNotificationById(id, userId)
                if (notification != null) {
                    call.respond(notification)
                } else {
                    call.respond(HttpStatusCode.NotFound, ErrorResponse("Notification not found"))
                }
            }

            put("/{id}/read") {
                val userId = call.requireCaller(callerIdentity) ?: return@put
                val id = call.parameters["id"] ?: return@put call.respond(
                    HttpStatusCode.BadRequest,
                    ErrorResponse("Notification ID is required"),
                )

                val success = notificationService.markAsRead(id, userId)
                if (success) {
                    call.respond(HttpStatusCode.NoContent)
                } else {
                    call.respond(HttpStatusCode.NotFound, ErrorResponse("Notification not found"))
                }
            }

            put("/read-all") {
                val userId = call.requireCaller(callerIdentity) ?: return@put

                val count = notificationService.markAllAsRead(userId)
                call.respond(MarkAllReadResponse(markedCount = count))
            }

            delete("/{id}") {
                val userId = call.requireCaller(callerIdentity) ?: return@delete
                val id = call.parameters["id"] ?: return@delete call.respond(
                    HttpStatusCode.BadRequest,
                    ErrorResponse("Notification ID is required"),
                )

                val success = notificationService.deleteNotification(id, userId)
                if (success) {
                    call.respond(HttpStatusCode.NoContent)
                } else {
                    call.respond(HttpStatusCode.NotFound, ErrorResponse("Notification not found"))
                }
            }
        }

        route("/api/v1/preferences") {
            get {
                val userId = call.requireCaller(callerIdentity) ?: return@get

                val preferences = notificationService.getPreferences(userId)
                call.respond(preferences)
            }

            put {
                val userId = call.requireCaller(callerIdentity) ?: return@put
                val request = call.receive<NotificationPreferenceRequest>()
                if (request.userId != null && request.userId != userId) {
                    call.respond(HttpStatusCode.Forbidden, ErrorResponse("Cannot update another user's preferences"))
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

        webSocket("/ws/notifications/{userId}") {
            val userId = callerIdentity.resolve(call, allowQueryToken = true)
            if (userId == null || userId != call.parameters["userId"]) {
                close(CloseReason(CloseReason.Codes.VIOLATED_POLICY, "authentication required"))
                return@webSocket
            }

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
    }
}
