package com.otterworks.notification.websocket

import com.otterworks.notification.model.Notification
import io.ktor.websocket.DefaultWebSocketSession
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.just
import io.mockk.mockk
import io.mockk.runs
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
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
        message = "msg",
        createdAt = "2024-01-01T00:00:00Z",
    )

    private fun session(): DefaultWebSocketSession = mockk<DefaultWebSocketSession>().also {
        coEvery { it.send(any()) } just runs
    }

    @Test
    fun `tracks connections per user`() {
        val a = session()
        val b = session()

        manager.addConnection("user-1", a)
        manager.addConnection("user-1", b)
        manager.addConnection("user-2", session())

        assertTrue(manager.isUserConnected("user-1"))
        assertEquals(2, manager.getConnectedUserCount())

        manager.removeConnection("user-1", a)
        assertTrue(manager.isUserConnected("user-1"))

        manager.removeConnection("user-1", b)
        assertFalse(manager.isUserConnected("user-1"))
        assertEquals(1, manager.getConnectedUserCount())
    }

    @Test
    fun `removing an unknown connection is a no-op`() {
        manager.removeConnection("nobody", session())
        assertEquals(0, manager.getConnectedUserCount())
    }

    @Test
    fun `push to a user without connections returns zero`() = runTest {
        assertEquals(0, manager.pushNotification("user-1", notification))
    }

    @Test
    fun `push sends the serialized notification to every session of the user only`() = runTest {
        val a = session()
        val b = session()
        val other = session()
        manager.addConnection("user-1", a)
        manager.addConnection("user-1", b)
        manager.addConnection("user-2", other)

        val frame = slot<Frame>()
        coEvery { a.send(capture(frame)) } just runs

        assertEquals(2, manager.pushNotification("user-1", notification))

        coVerify(exactly = 1) { a.send(any()) }
        coVerify(exactly = 1) { b.send(any()) }
        coVerify(exactly = 0) { other.send(any()) }
        val payload = (frame.captured as Frame.Text).readText()
        assertEquals(notification, Json.decodeFromString(Notification.serializer(), payload))
    }

    @Test
    fun `sessions that fail to send are dropped`() = runTest {
        val healthy = session()
        val dead = mockk<DefaultWebSocketSession>()
        coEvery { dead.send(any()) } throws RuntimeException("closed")
        manager.addConnection("user-1", healthy)
        manager.addConnection("user-1", dead)

        assertEquals(1, manager.pushNotification("user-1", notification))
        assertEquals(1, manager.pushNotification("user-1", notification))

        coVerify(exactly = 1) { dead.send(any()) }
        coVerify(exactly = 2) { healthy.send(any()) }
    }

    @Test
    fun `user is disconnected once every session has failed`() = runTest {
        val dead = mockk<DefaultWebSocketSession>()
        coEvery { dead.send(any()) } throws RuntimeException("closed")
        manager.addConnection("user-1", dead)

        assertEquals(0, manager.pushNotification("user-1", notification))
        assertFalse(manager.isUserConnected("user-1"))
    }
}
