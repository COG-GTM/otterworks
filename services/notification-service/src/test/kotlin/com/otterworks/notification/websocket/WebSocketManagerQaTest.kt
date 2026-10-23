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

class WebSocketManagerQaTest {

    private val manager = WebSocketManager()
    private val notification = Notification(
        id = "n1", userId = "u1", type = "file_shared", title = "T", message = "M", createdAt = "2026-01-01T00:00:00Z",
    )

    @Test
    fun `push to a user without connections delivers nothing`() = runTest {
        assertEquals(0, manager.pushNotification("u1", notification))
    }

    @Test
    fun `add and remove track connected users`() {
        val s = mockk<DefaultWebSocketSession>(relaxed = true)
        manager.addConnection("u1", s)
        assertTrue(manager.isUserConnected("u1"))
        assertEquals(1, manager.getConnectedUserCount())
        manager.removeConnection("u1", s)
        assertFalse(manager.isUserConnected("u1"))
        assertEquals(0, manager.getConnectedUserCount())
    }

    @Test
    fun `push sends JSON to every session of the user only`() = runTest {
        val a = mockk<DefaultWebSocketSession>(relaxed = true)
        val b = mockk<DefaultWebSocketSession>(relaxed = true)
        val other = mockk<DefaultWebSocketSession>(relaxed = true)
        val frame = slot<Frame>()
        coEvery { a.send(capture(frame)) } returns Unit
        manager.addConnection("u1", a)
        manager.addConnection("u1", b)
        manager.addConnection("u2", other)

        assertEquals(2, manager.pushNotification("u1", notification))
        assertTrue((frame.captured as Frame.Text).readText().contains("\"id\":\"n1\""))
        coVerify(exactly = 0) { other.send(any()) }
    }

    @Test
    fun `dead sessions are pruned after a failed push`() = runTest {
        val dead = mockk<DefaultWebSocketSession>()
        coEvery { dead.send(any()) } throws RuntimeException("closed")
        manager.addConnection("u1", dead)
        assertEquals(0, manager.pushNotification("u1", notification))
        assertFalse(manager.isUserConnected("u1"))
    }
}
