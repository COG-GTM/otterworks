package com.otterworks.notification.model

import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class NotificationEventTest {

    private val json = Json { encodeDefaults = true; ignoreUnknownKeys = true }

    @Test
    fun `EventType fromString resolves every known event and rejects anything else`() {
        assertEquals(EventType.file_shared, EventType.fromString("file_shared"))
        assertEquals(EventType.comment_added, EventType.fromString("comment_added"))
        assertEquals(EventType.document_edited, EventType.fromString("document_edited"))
        assertEquals(EventType.user_mentioned, EventType.fromString("user_mentioned"))
        assertNull(EventType.fromString("file_deleted"))
        assertNull(EventType.fromString(""))
        assertNull(EventType.fromString("FILE_SHARED"))
    }

    @Test
    fun `NotificationEvent round-trips through JSON and defaults its optional fields`() {
        val event = NotificationEvent(
            eventType = "file_shared",
            userId = "user-1",
            timestamp = "2024-01-01T00:00:00Z",
        )

        assertEquals("", event.sourceService)
        assertEquals(emptyMap(), event.metadata)

        val decoded = json.decodeFromString<NotificationEvent>(json.encodeToString(NotificationEvent.serializer(), event))
        assertEquals(event, decoded)
    }

    @Test
    fun `NotificationEvent keeps metadata entries through serialization`() {
        val event = NotificationEvent(
            eventType = "user_mentioned",
            sourceService = "document-service",
            userId = "user-1",
            actorId = "actor-1",
            resourceId = "doc-1",
            resourceType = "document",
            title = "You Were Mentioned",
            message = "actor-1 mentioned you",
            metadata = mapOf("documentTitle" to "Q1 Plan"),
            timestamp = "2024-01-01T00:00:00Z",
        )

        val decoded = json.decodeFromString<NotificationEvent>(json.encodeToString(NotificationEvent.serializer(), event))

        assertEquals("Q1 Plan", decoded.metadata["documentTitle"])
        assertEquals("document-service", decoded.sourceService)
    }

    @Test
    fun `SqsNotificationMessage decodes a partial payload using field defaults`() {
        val decoded = json.decodeFromString<SqsNotificationMessage>(
            """{"eventType":"comment_added","documentId":"doc-1","timestamp":"2024-01-01T00:00:00Z"}""",
        )

        assertEquals("comment_added", decoded.eventType)
        assertEquals("doc-1", decoded.documentId)
        assertEquals("", decoded.userId)
        assertEquals("", decoded.mentionedUserId)
    }

    @Test
    fun `Notification round-trips through JSON including delivery channels`() {
        val notification = Notification(
            id = "n-1",
            userId = "user-1",
            type = "file_shared",
            title = "File Shared With You",
            message = "A file has been shared with you.",
            resourceId = "file-1",
            resourceType = "file",
            actorId = "actor-1",
            read = true,
            deliveredVia = listOf("in_app", "email"),
            createdAt = "2024-01-01T00:00:00Z",
        )

        val decoded = json.decodeFromString<Notification>(json.encodeToString(Notification.serializer(), notification))

        assertEquals(notification, decoded)
        assertTrue(decoded.read)
    }

    @Test
    fun `Notification defaults to unread with no delivery channels`() {
        val notification = Notification(
            id = "n-2",
            userId = "user-1",
            type = "document_edited",
            title = "Document Edited",
            message = "doc-1 was edited",
            createdAt = "2024-01-01T00:00:00Z",
        )

        assertFalse(notification.read)
        assertEquals(emptyList(), notification.deliveredVia)
        assertEquals("", notification.resourceId)
    }

    @Test
    fun `NotificationPreference defaults enable the documented channels per event type`() {
        val preference = NotificationPreference(userId = "user-1")

        assertEquals(
            listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP, DeliveryChannel.PUSH),
            preference.channels["file_shared"],
        )
        assertEquals(listOf(DeliveryChannel.IN_APP, DeliveryChannel.PUSH), preference.channels["comment_added"])
        assertEquals(listOf(DeliveryChannel.IN_APP), preference.channels["document_edited"])
        assertEquals(
            listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP, DeliveryChannel.PUSH),
            preference.channels["user_mentioned"],
        )
    }

    @Test
    fun `NotificationPreference round-trips through JSON`() {
        val preference = NotificationPreference(
            userId = "user-1",
            channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL)),
        )

        val decoded = json.decodeFromString<NotificationPreference>(
            json.encodeToString(NotificationPreference.serializer(), preference),
        )

        assertEquals(preference, decoded)
    }

    @Test
    fun `PaginatedResponse and UnreadCountResponse serialize their pagination fields`() {
        val page = PaginatedResponse(
            data = listOf("a", "b"),
            total = 5,
            page = 1,
            pageSize = 2,
            hasMore = true,
        )

        val encoded = json.encodeToString(PaginatedResponse.serializer(String.serializer()), page)
        assertTrue(encoded.contains("\"total\":5"))
        assertTrue(encoded.contains("\"hasMore\":true"))

        val unread = UnreadCountResponse(userId = "user-1", unreadCount = 3)
        val decodedUnread = json.decodeFromString<UnreadCountResponse>(
            json.encodeToString(UnreadCountResponse.serializer(), unread),
        )
        assertEquals(unread, decodedUnread)
    }

    @Test
    fun `NotificationPreferenceRequest decodes channel names into enum values`() {
        val request = json.decodeFromString<NotificationPreferenceRequest>(
            """{"userId":"user-1","eventType":"file_shared","channels":["EMAIL","PUSH"]}""",
        )

        assertEquals("user-1", request.userId)
        assertEquals(listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH), request.channels)
    }
}
