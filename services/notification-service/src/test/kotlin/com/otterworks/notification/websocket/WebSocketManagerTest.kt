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
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class WebSocketManagerTest {

    private val manager = WebSocketManager()
    private val notification = Notification(id = "n1", userId = "u1", type = "file_shared", title = "t", message = "m", createdAt = "now")

    @Test
    fun `add and remove connections track users`() {
        val s1 = mockk<DefaultWebSocketSession>(relaxed = true)
        val s2 = mockk<DefaultWebSocketSession>(relaxed = true)

        manager.addConnection("u1", s1)
        manager.addConnection("u1", s2)
        manager.addConnection("u2", s1)
        assertEquals(2, manager.getConnectedUserCount())
        assertTrue(manager.isUserConnected("u1"))

        manager.removeConnection("u1", s1)
        assertTrue(manager.isUserConnected("u1"))
        manager.removeConnection("u1", s2)
        assertFalse(manager.isUserConnected("u1"))
        manager.removeConnection("nobody", s1)
        assertEquals(1, manager.getConnectedUserCount())
    }

    @Test
    fun `pushNotification returns zero for unknown user`() = runTest {
        assertEquals(0, manager.pushNotification("ghost", notification))
    }

    @Test
    fun `pushNotification sends JSON to live sessions and drops dead ones`() = runTest {
        val live = mockk<DefaultWebSocketSession>(relaxed = true)
        val dead = mockk<DefaultWebSocketSession>(relaxed = true)
        val frame = slot<Frame>()
        coEvery { live.send(capture(frame)) } returns Unit
        coEvery { dead.send(any<Frame>()) } throws IllegalStateException("closed")
        manager.addConnection("u1", live)
        manager.addConnection("u1", dead)

        assertEquals(1, manager.pushNotification("u1", notification))
        assertEquals(notification, Json.decodeFromString<Notification>((frame.captured as Frame.Text).readText()))

        assertEquals(1, manager.pushNotification("u1", notification))
        coVerify(exactly = 1) { dead.send(any<Frame>()) }
        assertTrue(manager.isUserConnected("u1"))
    }
}
