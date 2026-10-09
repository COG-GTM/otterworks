package com.otterworks.notification.websocket

import com.otterworks.notification.model.Notification
import io.ktor.websocket.DefaultWebSocketSession
import io.ktor.websocket.Frame
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import mu.KotlinLogging
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

private val logger = KotlinLogging.logger {}

class WebSocketManager(
    private val maxConnectionsPerUser: Int = Int.MAX_VALUE,
    private val maxConnections: Int = Int.MAX_VALUE,
) {

    private val connections = ConcurrentHashMap<String, MutableSet<DefaultWebSocketSession>>()
    private val totalConnections = AtomicInteger(0)

    private val json = Json {
        prettyPrint = false
        ignoreUnknownKeys = true
    }

    /**
     * Registers [session] for [userId] unless the per-user or service-wide
     * connection cap is reached. Returns false when the session was rejected.
     */
    fun tryAddConnection(userId: String, session: DefaultWebSocketSession): Boolean {
        var added = false
        connections.compute(userId) { _, existing ->
            val sessions = existing ?: ConcurrentHashMap.newKeySet()
            if (session in sessions) {
                added = true
            } else if (sessions.size < maxConnectionsPerUser && reserveSlot()) {
                sessions.add(session)
                added = true
            }
            if (sessions.isEmpty()) null else sessions
        }
        if (added) {
            logger.info { "WebSocket connected for user $userId (total: ${connections[userId]?.size ?: 0})" }
        } else {
            logger.warn { "WebSocket rejected for user $userId: connection limit reached" }
        }
        return added
    }

    fun removeConnection(userId: String, session: DefaultWebSocketSession) {
        connections.computeIfPresent(userId) { _, sessions ->
            if (sessions.remove(session)) totalConnections.decrementAndGet()
            if (sessions.isEmpty()) null else sessions
        }
        logger.info { "WebSocket disconnected for user $userId" }
    }

    fun getConnectionCount(): Int = totalConnections.get()

    private fun reserveSlot(): Boolean {
        while (true) {
            val current = totalConnections.get()
            if (current >= maxConnections) return false
            if (totalConnections.compareAndSet(current, current + 1)) return true
        }
    }

    suspend fun pushNotification(userId: String, notification: Notification): Int {
        val sessions = connections[userId] ?: return 0

        val payload = json.encodeToString(notification)
        val deadSessions = mutableListOf<DefaultWebSocketSession>()
        var successCount = 0

        for (session in sessions) {
            try {
                session.send(Frame.Text(payload))
                successCount++
                logger.debug { "Pushed notification ${notification.id} to user $userId via WebSocket" }
            } catch (e: Exception) {
                logger.warn { "Failed to push to WebSocket for user $userId: ${e.message}" }
                deadSessions.add(session)
            }
        }

        deadSessions.forEach { removeConnection(userId, it) }
        return successCount
    }

    fun getConnectedUserCount(): Int = connections.size

    fun isUserConnected(userId: String): Boolean = connections.containsKey(userId)
}
