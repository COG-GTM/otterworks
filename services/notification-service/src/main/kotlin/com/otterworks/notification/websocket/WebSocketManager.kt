package com.otterworks.notification.websocket

import com.otterworks.notification.model.Notification
import io.ktor.websocket.DefaultWebSocketSession
import io.ktor.websocket.Frame
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import mu.KotlinLogging
import java.util.concurrent.ConcurrentHashMap

private val logger = KotlinLogging.logger {}

class WebSocketManager(
    private val maxConnectionsPerClient: Int = Int.MAX_VALUE,
    private val maxConnections: Int = Int.MAX_VALUE,
) {

    private val connections = ConcurrentHashMap<String, MutableSet<DefaultWebSocketSession>>()

    // The path userId is unauthenticated, so limits are keyed on the peer
    // address rather than the user; otherwise anyone could fill a victim's slots.
    private val clientOfSession = HashMap<DefaultWebSocketSession, String>()
    private val connectionsPerClient = HashMap<String, Int>()
    private val lock = Any()

    private val json = Json {
        prettyPrint = false
        ignoreUnknownKeys = true
    }

    /**
     * Registers [session] for [userId] unless [clientAddress] or the service as
     * a whole has reached its connection cap. Returns false when rejected.
     */
    fun tryAddConnection(userId: String, clientAddress: String, session: DefaultWebSocketSession): Boolean {
        val added = synchronized(lock) {
            when {
                clientOfSession.containsKey(session) -> true
                clientOfSession.size >= maxConnections -> false
                (connectionsPerClient[clientAddress] ?: 0) >= maxConnectionsPerClient -> false
                else -> {
                    connectionsPerClient.merge(clientAddress, 1, Int::plus)
                    clientOfSession[session] = clientAddress
                    connections.computeIfAbsent(userId) { ConcurrentHashMap.newKeySet() }.add(session)
                    true
                }
            }
        }
        if (added) {
            logger.info { "WebSocket connected for user $userId (total: ${connections[userId]?.size ?: 0})" }
        } else {
            logger.warn { "WebSocket rejected for user $userId: connection limit reached" }
        }
        return added
    }

    fun removeConnection(userId: String, session: DefaultWebSocketSession) {
        synchronized(lock) {
            connections.computeIfPresent(userId) { _, sessions ->
                sessions.remove(session)
                if (sessions.isEmpty()) null else sessions
            }
            clientOfSession.remove(session)?.let { client ->
                connectionsPerClient.computeIfPresent(client) { _, count -> if (count <= 1) null else count - 1 }
            }
        }
        logger.info { "WebSocket disconnected for user $userId" }
    }

    fun getConnectionCount(): Int = synchronized(lock) { clientOfSession.size }

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
