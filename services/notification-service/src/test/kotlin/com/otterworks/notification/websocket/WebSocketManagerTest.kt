package com.otterworks.notification.websocket

import com.otterworks.notification.notification
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

    private fun session(): DefaultWebSocketSession = mockk(relaxed = true)

    @Test
    fun `connections are tracked per user and released when the last session goes away`() = runTest {
        val first = session()
        val second = session()

        assertEquals(0, manager.getConnectedUserCount())
        assertFalse(manager.isUserConnected("user-1"))

        manager.addConnection("user-1", first)
        manager.addConnection("user-1", second)
        manager.addConnection("user-2", session())

        assertEquals(2, manager.getConnectedUserCount())
        assertTrue(manager.isUserConnected("user-1"))

        manager.removeConnection("user-1", first)
        assertTrue(manager.isUserConnected("user-1"))

        manager.removeConnection("user-1", second)
        assertFalse(manager.isUserConnected("user-1"))
        assertEquals(1, manager.getConnectedUserCount())
    }

    @Test
    fun `removeConnection is a no-op for a user that was never connected`() = runTest {
        manager.removeConnection("ghost", session())

        assertEquals(0, manager.getConnectedUserCount())
    }

    @Test
    fun `pushNotification sends the serialized notification to every live session`() = runTest {
        val first = session()
        val second = session()
        manager.addConnection("user-1", first)
        manager.addConnection("user-1", second)
        val frame = slot<Frame>()
        coEvery { first.send(capture(frame)) } returns Unit

        val delivered = manager.pushNotification("user-1", notification(id = "n-42"))

        assertEquals(2, delivered)
        coVerify(exactly = 1) { second.send(any()) }
        val payload = Json.parseToJsonElement((frame.captured as Frame.Text).readText())
        assertEquals("n-42", payload.jsonStringField("id"))
        assertEquals("user-1", payload.jsonStringField("userId"))
    }

    @Test
    fun `pushNotification returns zero when the user has no session`() = runTest {
        assertEquals(0, manager.pushNotification("offline-user", notification()))
    }

    @Test
    fun `pushNotification drops sessions that fail and keeps the healthy ones`() = runTest {
        val healthy = session()
        val dead = session()
        coEvery { dead.send(any()) } throws IllegalStateException("socket closed")
        manager.addConnection("user-1", healthy)
        manager.addConnection("user-1", dead)

        assertEquals(1, manager.pushNotification("user-1", notification()))

        assertTrue(manager.isUserConnected("user-1"))
        assertEquals(1, manager.pushNotification("user-1", notification()))
    }

    private fun kotlinx.serialization.json.JsonElement.jsonStringField(name: String): String =
        (this as kotlinx.serialization.json.JsonObject).getValue(name)
            .let { (it as kotlinx.serialization.json.JsonPrimitive).content }
}
