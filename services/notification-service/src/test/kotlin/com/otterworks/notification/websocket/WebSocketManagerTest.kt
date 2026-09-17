package com.otterworks.notification.websocket

import com.otterworks.notification.model.Notification
import io.ktor.websocket.DefaultWebSocketSession
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class WebSocketManagerTest {

    private val manager = WebSocketManager()

    private val notification = Notification(
        id = "n-1",
        userId = "user-1",
        type = "file_shared",
        title = "File Shared With You",
        message = "A file has been shared with you.",
        resourceId = "file-1",
        resourceType = "file",
        actorId = "actor-1",
        read = false,
        deliveredVia = listOf("in_app"),
        createdAt = "2024-01-01T00:00:00Z",
    )

    private fun session() = mockk<DefaultWebSocketSession>(relaxed = true)

    @Test
    fun `addConnection tracks the user until the last session is removed`() {
        val first = session()
        val second = session()

        assertFalse(manager.isUserConnected("user-1"))
        assertEquals(0, manager.getConnectedUserCount())

        manager.addConnection("user-1", first)
        manager.addConnection("user-1", second)
        manager.addConnection("user-2", session())

        assertTrue(manager.isUserConnected("user-1"))
        assertEquals(2, manager.getConnectedUserCount())

        manager.removeConnection("user-1", first)
        assertTrue(manager.isUserConnected("user-1"))

        manager.removeConnection("user-1", second)
        assertFalse(manager.isUserConnected("user-1"))
        assertEquals(1, manager.getConnectedUserCount())
    }

    @Test
    fun `removeConnection is a no-op for an unknown user`() {
        manager.removeConnection("ghost", session())

        assertEquals(0, manager.getConnectedUserCount())
    }

    @Test
    fun `pushNotification sends the serialized notification to every session`() = runTest {
        val first = session()
        val second = session()
        manager.addConnection("user-1", first)
        manager.addConnection("user-1", second)
        val frame = slot<Frame>()
        coEvery { first.send(capture(frame)) } returns Unit

        assertEquals(2, manager.pushNotification("user-1", notification))

        val text = (frame.captured as Frame.Text).readText()
        assertTrue(text.contains("\"id\":\"n-1\""), text)
        assertTrue(text.contains("\"userId\":\"user-1\""), text)
        assertTrue(text.contains("\"type\":\"file_shared\""), text)
        coVerify(exactly = 1) { second.send(any<Frame>()) }
    }

    @Test
    fun `pushNotification returns zero when the user has no session`() = runTest {
        assertEquals(0, manager.pushNotification("offline-user", notification))
    }

    @Test
    fun `pushNotification drops sessions that fail to receive the frame`() = runTest {
        val healthy = session()
        val dead = session()
        coEvery { dead.send(any<Frame>()) } throws RuntimeException("closed")
        manager.addConnection("user-1", healthy)
        manager.addConnection("user-1", dead)

        assertEquals(1, manager.pushNotification("user-1", notification))

        assertTrue(manager.isUserConnected("user-1"))
        assertEquals(1, manager.pushNotification("user-1", notification))
        coVerify(exactly = 1) { dead.send(any<Frame>()) }
    }

    @Test
    fun `pushNotification forgets the user once all sessions are dead`() = runTest {
        val dead = session()
        coEvery { dead.send(any<Frame>()) } throws RuntimeException("closed")
        manager.addConnection("user-1", dead)

        assertEquals(0, manager.pushNotification("user-1", notification))

        assertFalse(manager.isUserConnected("user-1"))
        assertEquals(0, manager.getConnectedUserCount())
    }
}
