package com.otterworks.notification.websocket

import com.otterworks.notification.model.Notification
import io.ktor.websocket.DefaultWebSocketSession
import io.ktor.websocket.Frame
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
        id = "notif-1",
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

    @Test
    fun `addConnection registers the user as connected`() {
        val session = mockk<DefaultWebSocketSession>(relaxed = true)

        manager.addConnection("user-1", session)

        assertTrue(manager.isUserConnected("user-1"))
        assertEquals(1, manager.getConnectedUserCount())
    }

    @Test
    fun `addConnection keeps multiple sessions for the same user`() {
        manager.addConnection("user-1", mockk(relaxed = true))
        manager.addConnection("user-1", mockk(relaxed = true))

        assertEquals(1, manager.getConnectedUserCount())
    }

    @Test
    fun `removeConnection drops the user once the last session goes away`() {
        val first = mockk<DefaultWebSocketSession>(relaxed = true)
        val second = mockk<DefaultWebSocketSession>(relaxed = true)
        manager.addConnection("user-1", first)
        manager.addConnection("user-1", second)

        manager.removeConnection("user-1", first)
        assertTrue(manager.isUserConnected("user-1"))

        manager.removeConnection("user-1", second)
        assertFalse(manager.isUserConnected("user-1"))
        assertEquals(0, manager.getConnectedUserCount())
    }

    @Test
    fun `removeConnection is a no-op for an unknown user`() {
        manager.removeConnection("ghost", mockk(relaxed = true))

        assertEquals(0, manager.getConnectedUserCount())
    }

    @Test
    fun `pushNotification returns zero when the user has no sessions`() = runTest {
        assertEquals(0, manager.pushNotification("user-1", notification))
    }

    @Test
    fun `pushNotification sends the serialized notification to every session`() = runTest {
        val session = mockk<DefaultWebSocketSession>(relaxed = true)
        manager.addConnection("user-1", session)
        val frame = slot<Frame>()
        coEvery { session.send(capture(frame)) } returns Unit

        val delivered = manager.pushNotification("user-1", notification)

        assertEquals(1, delivered)
        coVerify(exactly = 1) { session.send(any<Frame>()) }
        val payload = String((frame.captured as Frame.Text).data)
        assertTrue(payload.contains("\"id\":\"notif-1\""))
        assertTrue(payload.contains("\"userId\":\"user-1\""))
    }

    @Test
    fun `pushNotification drops sessions that fail to receive the frame`() = runTest {
        val healthy = mockk<DefaultWebSocketSession>(relaxed = true)
        val dead = mockk<DefaultWebSocketSession>(relaxed = true)
        coEvery { dead.send(any<Frame>()) } throws IllegalStateException("closed")
        manager.addConnection("user-1", healthy)
        manager.addConnection("user-1", dead)

        val delivered = manager.pushNotification("user-1", notification)

        assertEquals(1, delivered)
        assertTrue(manager.isUserConnected("user-1"))
    }

    @Test
    fun `pushNotification removes the user when every session is dead`() = runTest {
        val dead = mockk<DefaultWebSocketSession>(relaxed = true)
        coEvery { dead.send(any<Frame>()) } throws IllegalStateException("closed")
        manager.addConnection("user-1", dead)

        assertEquals(0, manager.pushNotification("user-1", notification))
        assertFalse(manager.isUserConnected("user-1"))
    }
}
