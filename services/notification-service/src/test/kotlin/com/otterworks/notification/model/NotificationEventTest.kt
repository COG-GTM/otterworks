package com.otterworks.notification.model

import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class NotificationEventTest {

    private val json = Json { encodeDefaults = true }
    private val lenient = Json { ignoreUnknownKeys = true }

    @Test
    fun `EventType maps known names and rejects everything else`() {
        assertEquals(EventType.file_shared, EventType.fromString("file_shared"))
        assertEquals(EventType.comment_added, EventType.fromString("comment_added"))
        assertEquals(EventType.document_edited, EventType.fromString("document_edited"))
        assertEquals(EventType.user_mentioned, EventType.fromString("user_mentioned"))
        assertNull(EventType.fromString("File_Shared"))
        assertNull(EventType.fromString(""))
        assertEquals(4, EventType.entries.size)
    }

    @Test
    fun `EventType round-trips through JSON`() {
        assertEquals("\"user_mentioned\"", json.encodeToString(EventType.user_mentioned))
        assertEquals(EventType.comment_added, json.decodeFromString<EventType>("\"comment_added\""))
    }

    @Test
    fun `DeliveryChannel round-trips through JSON`() {
        assertEquals("\"EMAIL\"", json.encodeToString(DeliveryChannel.EMAIL))
        assertEquals(DeliveryChannel.PUSH, json.decodeFromString<DeliveryChannel>("\"PUSH\""))
        assertEquals(listOf("EMAIL", "IN_APP", "PUSH"), DeliveryChannel.entries.map { it.name })
    }

    @Test
    fun `NotificationEvent serializes every field and restores defaults for the optional ones`() {
        val event = NotificationEvent(
            eventType = "file_shared",
            sourceService = "file-service",
            userId = "user-1",
            actorId = "actor-1",
            resourceId = "file-1",
            resourceType = "file",
            title = "File Shared",
            message = "A file has been shared with you.",
            metadata = mapOf("fileName" to "q3.pdf"),
            timestamp = "2024-01-01T00:00:00Z",
        )

        val encoded = json.encodeToString(event)
        assertTrue(encoded.contains("\"sourceService\":\"file-service\""))
        assertTrue(encoded.contains("\"metadata\":{\"fileName\":\"q3.pdf\"}"))
        assertEquals(event, json.decodeFromString<NotificationEvent>(encoded))

        val minimal = lenient.decodeFromString<NotificationEvent>(
            """{"eventType":"comment_added","userId":"user-9","timestamp":"2024-01-02T00:00:00Z","extra":1}""",
        )
        assertEquals("", minimal.sourceService)
        assertEquals("", minimal.actorId)
        assertEquals("", minimal.resourceId)
        assertEquals("", minimal.resourceType)
        assertEquals("", minimal.title)
        assertEquals("", minimal.message)
        assertEquals(emptyMap(), minimal.metadata)
    }

    @Test
    fun `SqsNotificationMessage restores defaults for absent fields`() {
        val message = SqsNotificationMessage(
            eventType = "user_mentioned",
            fileId = "f-1",
            ownerId = "o-1",
            sharedWithUserId = "s-1",
            documentId = "d-1",
            commentId = "c-1",
            userId = "u-1",
            actorId = "a-1",
            mentionedUserId = "m-1",
            timestamp = "2024-01-01T00:00:00Z",
        )

        assertEquals(message, json.decodeFromString(json.encodeToString(message)))

        val minimal = json.decodeFromString<SqsNotificationMessage>(
            """{"eventType":"file_shared","timestamp":"2024-01-01T00:00:00Z"}""",
        )
        assertEquals(
            SqsNotificationMessage(eventType = "file_shared", timestamp = "2024-01-01T00:00:00Z"),
            minimal,
        )
        assertNotEquals(message, minimal)
        assertNotEquals(message.hashCode(), minimal.hashCode())
        assertTrue(message.toString().contains("mentionedUserId=m-1"))
    }

    @Test
    fun `Notification round-trips and copies structurally`() {
        val notification = Notification(
            id = "n-1",
            userId = "user-1",
            type = "file_shared",
            title = "File Shared",
            message = "A file has been shared with you.",
            resourceId = "file-1",
            resourceType = "file",
            actorId = "actor-1",
            read = false,
            deliveredVia = listOf("in_app", "email"),
            createdAt = "2024-01-01T00:00:00Z",
        )

        val decoded = json.decodeFromString<Notification>(json.encodeToString(notification))
        assertEquals(notification, decoded)
        assertEquals(notification.hashCode(), decoded.hashCode())

        val read = notification.copy(read = true, deliveredVia = notification.deliveredVia + "push")
        assertNotEquals(notification, read)
        assertTrue(read.read)
        assertEquals(listOf("in_app", "email", "push"), read.deliveredVia)
        assertTrue(notification.toString().contains("id=n-1"))

        val minimal = json.decodeFromString<Notification>(
            """{"id":"n-2","userId":"u","type":"t","title":"x","message":"y","createdAt":"2024-01-01T00:00:00Z"}""",
        )
        assertEquals("", minimal.resourceId)
        assertEquals("", minimal.resourceType)
        assertEquals("", minimal.actorId)
        assertEquals(false, minimal.read)
        assertEquals(emptyList(), minimal.deliveredVia)
    }

    @Test
    fun `NotificationPreference defaults describe the per-event channel matrix`() {
        val preference = NotificationPreference(userId = "user-1")

        assertEquals(
            listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP, DeliveryChannel.PUSH),
            preference.channels["file_shared"],
        )
        assertEquals(
            listOf(DeliveryChannel.IN_APP, DeliveryChannel.PUSH),
            preference.channels["comment_added"],
        )
        assertEquals(listOf(DeliveryChannel.IN_APP), preference.channels["document_edited"])
        assertEquals(
            listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP, DeliveryChannel.PUSH),
            preference.channels["user_mentioned"],
        )

        val decoded = json.decodeFromString<NotificationPreference>(json.encodeToString(preference))
        assertEquals(preference, decoded)

        val stored = json.decodeFromString<NotificationPreference>("""{"userId":"user-2"}""")
        assertEquals(preference.channels, stored.channels)
        assertEquals("user-2", stored.userId)

        val overridden = preference.copy(channels = mapOf("file_shared" to emptyList()))
        assertNotEquals(preference, overridden)
        assertEquals(emptyList(), overridden.channels["file_shared"])
        assertTrue(preference.toString().contains("userId=user-1"))
    }

    @Test
    fun `PaginatedResponse serializes its element type`() {
        val page = PaginatedResponse(
            data = listOf("a", "b"),
            total = 5,
            page = 1,
            pageSize = 2,
            hasMore = true,
        )

        val serializer = PaginatedResponse.serializer(String.serializer())
        val encoded = json.encodeToString(serializer, page)
        assertTrue(encoded.contains("\"total\":5"))
        assertTrue(encoded.contains("\"hasMore\":true"))
        assertEquals(page, json.decodeFromString(serializer, encoded))
        assertEquals(page.hashCode(), page.copy().hashCode())
        assertTrue(page.toString().contains("pageSize=2"))
    }

    @Test
    fun `UnreadCountResponse and NotificationPreferenceRequest round-trip`() {
        val unread = UnreadCountResponse(userId = "user-1", unreadCount = 3)
        assertEquals("""{"userId":"user-1","unreadCount":3}""", json.encodeToString(unread))
        assertEquals(unread, json.decodeFromString<UnreadCountResponse>(json.encodeToString(unread)))
        assertNotEquals(unread, unread.copy(unreadCount = 4))
        assertTrue(unread.toString().contains("unreadCount=3"))

        val request = NotificationPreferenceRequest(
            userId = "user-1",
            eventType = "file_shared",
            channels = listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH),
        )
        val encoded = json.encodeToString(request)
        assertTrue(encoded.contains("\"channels\":[\"EMAIL\",\"PUSH\"]"))
        assertEquals(request, json.decodeFromString<NotificationPreferenceRequest>(encoded))
        assertEquals(request.hashCode(), request.copy().hashCode())
        assertTrue(request.toString().contains("eventType=file_shared"))
    }
}
