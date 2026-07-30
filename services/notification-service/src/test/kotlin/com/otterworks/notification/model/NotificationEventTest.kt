package com.otterworks.notification.model

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class NotificationEventTest {

    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    @Test
    fun `EventType maps known names and rejects unknown ones`() {
        assertEquals(EventType.file_shared, EventType.fromString("file_shared"))
        assertEquals(EventType.comment_added, EventType.fromString("comment_added"))
        assertEquals(EventType.document_edited, EventType.fromString("document_edited"))
        assertEquals(EventType.user_mentioned, EventType.fromString("user_mentioned"))
        assertNull(EventType.fromString("file_deleted"))
        assertNull(EventType.fromString(""))
        assertEquals(4, EventType.entries.size)
        assertEquals(EventType.file_shared, EventType.valueOf("file_shared"))
        assertEquals("""["file_shared"]""", json.encodeToString(listOf(EventType.file_shared)))
    }

    @Test
    fun `DeliveryChannel round-trips through JSON`() {
        assertEquals(3, DeliveryChannel.entries.size)
        assertEquals(DeliveryChannel.PUSH, DeliveryChannel.valueOf("PUSH"))
        val encoded = json.encodeToString(DeliveryChannel.entries.toList())
        assertEquals("""["EMAIL","IN_APP","PUSH"]""", encoded)
        assertEquals(DeliveryChannel.entries.toList(), json.decodeFromString<List<DeliveryChannel>>(encoded))
    }

    @Test
    fun `NotificationEvent round-trips with defaults and with every field set`() {
        val minimal = NotificationEvent(
            eventType = "file_shared",
            userId = "user-1",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals(minimal, json.decodeFromString<NotificationEvent>(json.encodeToString(minimal)))
        assertEquals("", minimal.sourceService)
        assertEquals(emptyMap(), minimal.metadata)

        val full = minimal.copy(
            sourceService = "file-service",
            actorId = "actor-1",
            resourceId = "file-1",
            resourceType = "file",
            title = "File Shared",
            message = "A file has been shared with you.",
            metadata = mapOf("fileName" to "q3.pdf"),
        )
        val decoded = json.decodeFromString<NotificationEvent>(json.encodeToString(full))
        assertEquals(full, decoded)
        assertEquals(full.hashCode(), decoded.hashCode())
        assertFalse(full == minimal)
        assertTrue(full.toString().contains("file-service"))
        assertEquals("file_shared", full.component1())
        assertEquals(mapOf("fileName" to "q3.pdf"), full.metadata)
    }

    @Test
    fun `SqsNotificationMessage round-trips with defaults and with every field set`() {
        val minimal = SqsNotificationMessage(eventType = "file_shared", timestamp = "2024-01-01T00:00:00Z")
        assertEquals(minimal, json.decodeFromString<SqsNotificationMessage>(json.encodeToString(minimal)))
        assertEquals("", minimal.fileId)
        assertEquals("", minimal.ownerId)
        assertEquals("", minimal.sharedWithUserId)
        assertEquals("", minimal.documentId)
        assertEquals("", minimal.commentId)
        assertEquals("", minimal.userId)
        assertEquals("", minimal.actorId)
        assertEquals("", minimal.mentionedUserId)

        val full = minimal.copy(
            fileId = "file-1",
            ownerId = "owner-1",
            sharedWithUserId = "user-2",
            documentId = "doc-1",
            commentId = "comment-1",
            userId = "user-1",
            actorId = "actor-1",
            mentionedUserId = "user-3",
        )
        val decoded = json.decodeFromString<SqsNotificationMessage>(json.encodeToString(full))
        assertEquals(full, decoded)
        assertEquals(full.hashCode(), decoded.hashCode())
        assertFalse(full == minimal)
        assertTrue(full.toString().contains("comment-1"))
        assertEquals("2024-01-01T00:00:00Z", full.component10())
    }

    @Test
    fun `Notification round-trips with defaults and with every field set`() {
        val minimal = Notification(
            id = "notif-1",
            userId = "user-1",
            type = "file_shared",
            title = "File Shared",
            message = "A file has been shared with you.",
            createdAt = "2024-01-01T00:00:00Z",
        )
        assertEquals(minimal, json.decodeFromString<Notification>(json.encodeToString(minimal)))
        assertFalse(minimal.read)
        assertEquals(emptyList(), minimal.deliveredVia)

        val full = minimal.copy(
            resourceId = "file-1",
            resourceType = "file",
            actorId = "actor-1",
            read = true,
            deliveredVia = listOf("in_app", "email", "push"),
        )
        val decoded = json.decodeFromString<Notification>(json.encodeToString(full))
        assertEquals(full, decoded)
        assertEquals(full.hashCode(), decoded.hashCode())
        assertFalse(full == minimal)
        assertTrue(full.toString().contains("notif-1"))
        assertEquals("notif-1", full.component1())
        assertEquals(listOf("in_app", "email", "push"), full.component10())
    }

    @Test
    fun `NotificationPreference defaults cover every event type`() {
        val defaults = NotificationPreference(userId = "user-1")

        assertEquals(
            listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP, DeliveryChannel.PUSH),
            defaults.channels["file_shared"],
        )
        assertEquals(
            listOf(DeliveryChannel.IN_APP, DeliveryChannel.PUSH),
            defaults.channels["comment_added"],
        )
        assertEquals(listOf(DeliveryChannel.IN_APP), defaults.channels["document_edited"])
        assertEquals(
            listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP, DeliveryChannel.PUSH),
            defaults.channels["user_mentioned"],
        )
        assertNull(defaults.channels["file_deleted"])

        val decoded = json.decodeFromString<NotificationPreference>(json.encodeToString(defaults))
        assertEquals(defaults, decoded)
        assertEquals(defaults.hashCode(), decoded.hashCode())
        assertEquals("user-1", defaults.component1())
        assertTrue(defaults.toString().contains("user-1"))

        val overridden = defaults.copy(channels = mapOf("file_shared" to emptyList()))
        assertFalse(overridden == defaults)
        assertEquals(emptyList(), overridden.channels["file_shared"])
    }

    @Test
    fun `PaginatedResponse round-trips a page of notifications`() {
        val page = PaginatedResponse(
            data = listOf(
                Notification(
                    id = "notif-1",
                    userId = "user-1",
                    type = "file_shared",
                    title = "File Shared",
                    message = "A file has been shared with you.",
                    createdAt = "2024-01-01T00:00:00Z",
                )
            ),
            total = 1,
            page = 1,
            pageSize = 20,
            hasMore = false,
        )

        val decoded = json.decodeFromString<PaginatedResponse<Notification>>(json.encodeToString(page))
        assertEquals(page, decoded)
        assertEquals(page.hashCode(), decoded.hashCode())
        assertFalse(page == page.copy(hasMore = true))
        assertTrue(page.toString().contains("pageSize=20"))
        assertEquals(1, page.component2())
    }

    @Test
    fun `UnreadCountResponse round-trips`() {
        val response = UnreadCountResponse(userId = "user-1", unreadCount = 5)

        assertEquals("""{"userId":"user-1","unreadCount":5}""", json.encodeToString(response))
        assertEquals(response, json.decodeFromString<UnreadCountResponse>(json.encodeToString(response)))
        assertEquals(response.hashCode(), UnreadCountResponse("user-1", 5).hashCode())
        assertFalse(response == response.copy(unreadCount = 6))
        assertTrue(response.toString().contains("unreadCount=5"))
        assertEquals(5, response.component2())
    }

    @Test
    fun `NotificationPreferenceRequest round-trips`() {
        val request = NotificationPreferenceRequest(
            userId = "user-1",
            eventType = "file_shared",
            channels = listOf(DeliveryChannel.EMAIL),
        )

        val decoded = json.decodeFromString<NotificationPreferenceRequest>(json.encodeToString(request))
        assertEquals(request, decoded)
        assertEquals(request.hashCode(), decoded.hashCode())
        assertFalse(request == request.copy(eventType = "comment_added"))
        assertTrue(request.toString().contains("file_shared"))
        assertEquals("user-1", request.component1())
        assertEquals(listOf(DeliveryChannel.EMAIL), request.component3())
    }
}
