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
        createdAt = "2024-01-01T00:00:00Z",
    )

    private fun session() = mockk<DefaultWebSocketSession>(relaxed = true)

    @Test
    fun `addConnection registers the user and removeConnection drops it again`() {
        val session = session()
        assertFalse(manager.isUserConnected("user-1"))

        manager.addConnection("user-1", session)

        assertTrue(manager.isUserConnected("user-1"))
        assertEquals(1, manager.getConnectedUserCount())

        manager.removeConnection("user-1", session)

        assertFalse(manager.isUserConnected("user-1"))
        assertEquals(0, manager.getConnectedUserCount())
    }

    @Test
    fun `removeConnection keeps the user connected while other sessions remain`() {
        val first = session()
        val second = session()
        manager.addConnection("user-1", first)
        manager.addConnection("user-1", second)

        manager.removeConnection("user-1", first)

        assertTrue(manager.isUserConnected("user-1"))
        assertEquals(1, manager.getConnectedUserCount())
    }

    @Test
    fun `removeConnection for an unknown user is a no-op`() {
        manager.removeConnection("ghost", session())

        assertEquals(0, manager.getConnectedUserCount())
    }

    @Test
    fun `pushNotification sends the serialized notification to every session`() = runTest {
        val first = session()
        val second = session()
        val frame = slot<Frame>()
        coEvery { first.send(capture(frame)) } returns Unit
        manager.addConnection("user-1", first)
        manager.addConnection("user-1", second)

        val delivered = manager.pushNotification("user-1", notification)

        assertEquals(2, delivered)
        val payload = (frame.captured as Frame.Text).readText()
        assertTrue(payload.contains("\"id\":\"n-1\""))
        assertTrue(payload.contains("\"userId\":\"user-1\""))
        coVerify(exactly = 1) { second.send(any<Frame>()) }
    }

    @Test
    fun `pushNotification returns zero when the user has no open session`() = runTest {
        assertEquals(0, manager.pushNotification("offline-user", notification))
    }

    @Test
    fun `pushNotification evicts sessions that fail to receive the frame`() = runTest {
        val healthy = session()
        val broken = session()
        coEvery { broken.send(any<Frame>()) } throws RuntimeException("socket closed")
        manager.addConnection("user-1", healthy)
        manager.addConnection("user-1", broken)

        val delivered = manager.pushNotification("user-1", notification)

        assertEquals(1, delivered)
        assertTrue(manager.isUserConnected("user-1"))

        coEvery { healthy.send(any<Frame>()) } throws RuntimeException("socket closed")
        assertEquals(0, manager.pushNotification("user-1", notification))
        assertFalse(manager.isUserConnected("user-1"))
    }
}
