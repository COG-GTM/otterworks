package com.otterworks.notification.websocket

import com.otterworks.notification.model.Notification
import io.ktor.websocket.DefaultWebSocketSession
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class WebSocketManagerTest {

    private val notification = Notification(
        id = "n-1",
        userId = "user-1",
        type = "file_shared",
        title = "File shared",
        message = "A file was shared with you",
        createdAt = "2024-01-01T00:00:00Z",
    )

    @Test
    fun `pushNotification returns 0 when user has no connections`() = runTest {
        val manager = WebSocketManager()

        assertEquals(0, manager.pushNotification("user-1", notification))
    }

    @Test
    fun `pushNotification sends to every session of the user`() = runTest {
        val manager = WebSocketManager()
        val first = mockk<DefaultWebSocketSession>(relaxed = true)
        val second = mockk<DefaultWebSocketSession>(relaxed = true)
        manager.addConnection("user-1", first)
        manager.addConnection("user-1", second)

        assertEquals(2, manager.pushNotification("user-1", notification))
        coVerify(exactly = 1) { first.send(any()) }
        coVerify(exactly = 1) { second.send(any()) }
    }

    @Test
    fun `pushNotification drops failed sessions and keeps healthy ones`() = runTest {
        val manager = WebSocketManager()
        val healthy = mockk<DefaultWebSocketSession>(relaxed = true)
        val dead = mockk<DefaultWebSocketSession>(relaxed = true)
        coEvery { dead.send(any()) } throws IllegalStateException("closed")
        manager.addConnection("user-1", healthy)
        manager.addConnection("user-1", dead)

        assertEquals(1, manager.pushNotification("user-1", notification))
        assertTrue(manager.isUserConnected("user-1"))

        assertEquals(1, manager.pushNotification("user-1", notification))
        coVerify(exactly = 1) { dead.send(any()) }
        coVerify(exactly = 2) { healthy.send(any()) }
    }

    @Test
    fun `pushNotification sends to every session present at call time even if others disconnect mid-push`() = runTest {
        val manager = WebSocketManager()
        val sessions = List(3) { mockk<DefaultWebSocketSession>(relaxed = true) }
        sessions.forEach { session ->
            coEvery { session.send(any()) } answers {
                sessions.filter { it !== session }.forEach { manager.removeConnection("user-1", it) }
            }
            manager.addConnection("user-1", session)
        }

        assertEquals(3, manager.pushNotification("user-1", notification))
        sessions.forEach { coVerify(exactly = 1) { it.send(any()) } }
    }

    @Test
    fun `pushNotification disconnects user when all sessions fail`() = runTest {
        val manager = WebSocketManager()
        val dead = mockk<DefaultWebSocketSession>(relaxed = true)
        coEvery { dead.send(any()) } throws IllegalStateException("closed")
        manager.addConnection("user-1", dead)

        assertEquals(0, manager.pushNotification("user-1", notification))
        assertFalse(manager.isUserConnected("user-1"))
        assertEquals(0, manager.getConnectedUserCount())
    }
}
