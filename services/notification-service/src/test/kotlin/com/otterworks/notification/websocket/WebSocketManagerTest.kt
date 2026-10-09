package com.otterworks.notification.websocket

import io.ktor.websocket.DefaultWebSocketSession
import io.mockk.mockk
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class WebSocketManagerTest {

    private fun session(): DefaultWebSocketSession = mockk(relaxed = true)

    @Test
    fun `rejects connections beyond the per-client cap`() {
        val manager = WebSocketManager(maxConnectionsPerClient = 2, maxConnections = 10)

        assertTrue(manager.tryAddConnection("u1", "10.0.0.1", session()))
        assertTrue(manager.tryAddConnection("u2", "10.0.0.1", session()))
        assertFalse(manager.tryAddConnection("u3", "10.0.0.1", session()))
        assertFalse(manager.isUserConnected("u3"))
        assertTrue(manager.tryAddConnection("u3", "10.0.0.2", session()))
        assertEquals(3, manager.getConnectionCount())
    }

    @Test
    fun `one client cannot exhaust another client's slots for the same userId`() {
        val manager = WebSocketManager(maxConnectionsPerClient = 2, maxConnections = 10)

        repeat(2) { assertTrue(manager.tryAddConnection("victim", "203.0.113.9", session())) }
        assertFalse(manager.tryAddConnection("victim", "203.0.113.9", session()))

        assertTrue(manager.tryAddConnection("victim", "10.0.0.5", session()))
    }

    @Test
    fun `rejects connections beyond the service-wide cap`() {
        val manager = WebSocketManager(maxConnectionsPerClient = 5, maxConnections = 2)

        assertTrue(manager.tryAddConnection("u1", "10.0.0.1", session()))
        assertTrue(manager.tryAddConnection("u2", "10.0.0.2", session()))
        assertFalse(manager.tryAddConnection("u3", "10.0.0.3", session()))
        assertEquals(2, manager.getConnectionCount())
    }

    @Test
    fun `removing a connection frees its slot`() {
        val manager = WebSocketManager(maxConnectionsPerClient = 1, maxConnections = 1)
        val first = session()

        assertTrue(manager.tryAddConnection("u1", "10.0.0.1", first))
        assertFalse(manager.tryAddConnection("u1", "10.0.0.1", session()))

        manager.removeConnection("u1", first)
        manager.removeConnection("u1", first)

        assertEquals(0, manager.getConnectionCount())
        assertFalse(manager.isUserConnected("u1"))
        assertTrue(manager.tryAddConnection("u1", "10.0.0.1", session()))
    }

    @Test
    fun `re-adding the same session does not consume another slot`() {
        val manager = WebSocketManager(maxConnectionsPerClient = 1, maxConnections = 1)
        val only = session()

        assertTrue(manager.tryAddConnection("u1", "10.0.0.1", only))
        assertTrue(manager.tryAddConnection("u1", "10.0.0.1", only))
        assertEquals(1, manager.getConnectionCount())
    }
}
