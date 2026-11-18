package com.otterworks.notification.model

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class NotificationEventTest {

    private val json = Json { encodeDefaults = true }

    @Test
    fun `EventType fromString resolves known names only`() {
        EventType.entries.forEach { assertEquals(it, EventType.fromString(it.name)) }
        assertNull(EventType.fromString("unknown"))
    }

    @Test
    fun `NotificationEvent round trips with defaults`() {
        val minimal = Json.decodeFromString<NotificationEvent>("""{"eventType":"file_shared","userId":"u1","timestamp":"t"}""")
        assertEquals(NotificationEvent(eventType = "file_shared", userId = "u1", timestamp = "t"), minimal)
        assertEquals("", minimal.sourceService)
        assertEquals(emptyMap(), minimal.metadata)

        val full = NotificationEvent("comment_added", "doc", "u1", "a", "r", "doc", "T", "M", mapOf("k" to "v"), "t")
        assertEquals(full, json.decodeFromString(json.encodeToString(NotificationEvent.serializer(), full)))
    }

    @Test
    fun `SqsNotificationMessage round trips`() {
        val msg = SqsNotificationMessage("user_mentioned", "f", "o", "s", "d", "c", "u", "a", "m", "t")
        assertEquals(msg, json.decodeFromString(json.encodeToString(SqsNotificationMessage.serializer(), msg)))
    }

    @Test
    fun `Notification and response types round trip`() {
        val n = Notification("n1", "u1", "file_shared", "t", "m", "r", "file", "a", true, listOf("in_app"), "now")
        assertEquals(n, json.decodeFromString(json.encodeToString(Notification.serializer(), n)))

        val page = PaginatedResponse(listOf(n), 1, 1, 20, false)
        assertEquals(page, json.decodeFromString(json.encodeToString(PaginatedResponse.serializer(Notification.serializer()), page)))

        val unread = UnreadCountResponse("u1", 2)
        assertEquals(unread, json.decodeFromString(json.encodeToString(UnreadCountResponse.serializer(), unread)))

        val req = NotificationPreferenceRequest("u1", "file_shared", listOf(DeliveryChannel.EMAIL))
        assertEquals(req, json.decodeFromString(json.encodeToString(NotificationPreferenceRequest.serializer(), req)))
    }

    @Test
    fun `NotificationPreference defaults cover every event type`() {
        val prefs = NotificationPreference("u1")
        assertEquals(EventType.entries.map { it.name }.toSet(), prefs.channels.keys)
        assertEquals(prefs, json.decodeFromString(json.encodeToString(NotificationPreference.serializer(), prefs)))
        assertEquals(prefs, Json.decodeFromString<NotificationPreference>("""{"userId":"u1"}"""))
    }
}
