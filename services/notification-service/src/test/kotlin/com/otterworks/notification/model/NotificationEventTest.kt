package com.otterworks.notification.model

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
        assertNull(EventType.fromString("File_Shared"))
        assertNull(EventType.fromString(""))
        assertNull(EventType.fromString("account_deleted"))
    }

    @Test
    fun `EventType round-trips through JSON`() {
        assertEquals("\"user_mentioned\"", json.encodeToString(EventType.serializer(), EventType.user_mentioned))
        assertEquals(
            EventType.document_edited,
            json.decodeFromString(EventType.serializer(), "\"document_edited\""),
        )
    }

    @Test
    fun `NotificationEvent decodes optional fields to empty defaults`() {
        val event = json.decodeFromString(
            NotificationEvent.serializer(),
            """{"eventType":"file_shared","userId":"user-1","timestamp":"2024-01-01T00:00:00Z"}""",
        )

        assertEquals("file_shared", event.eventType)
        assertEquals("user-1", event.userId)
        assertEquals("2024-01-01T00:00:00Z", event.timestamp)
        assertEquals("", event.sourceService)
        assertEquals("", event.actorId)
        assertEquals("", event.resourceId)
        assertEquals("", event.resourceType)
        assertEquals("", event.title)
        assertEquals("", event.message)
        assertEquals(emptyMap(), event.metadata)
    }

    @Test
    fun `NotificationEvent round-trips metadata`() {
        val event = NotificationEvent(
            eventType = "user_mentioned",
            sourceService = "document-service",
            userId = "user-1",
            actorId = "actor-1",
            resourceId = "doc-1",
            resourceType = "document",
            title = "You Were Mentioned",
            message = "You were mentioned by actor-1.",
            metadata = mapOf("commentId" to "c-1"),
            timestamp = "2024-01-01T00:00:00Z",
        )

        val decoded = json.decodeFromString(
            NotificationEvent.serializer(),
            json.encodeToString(NotificationEvent.serializer(), event),
        )

        assertEquals(event, decoded)
        assertEquals("c-1", decoded.metadata["commentId"])
    }

    @Test
    fun `SqsNotificationMessage round-trips every routing field`() {
        val message = SqsNotificationMessage(
            eventType = "comment_added",
            fileId = "file-1",
            ownerId = "owner-1",
            sharedWithUserId = "shared-1",
            documentId = "doc-1",
            commentId = "c-1",
            userId = "user-1",
            actorId = "actor-1",
            mentionedUserId = "mentioned-1",
            timestamp = "2024-01-01T00:00:00Z",
        )

        val encoded = json.encodeToString(SqsNotificationMessage.serializer(), message)
        val decoded = json.decodeFromString(SqsNotificationMessage.serializer(), encoded)

        assertEquals(message, decoded)
        assertTrue(encoded.contains("\"mentionedUserId\":\"mentioned-1\""), encoded)
        assertEquals(
            SqsNotificationMessage(eventType = "x", timestamp = "t"),
            json.decodeFromString(
                SqsNotificationMessage.serializer(),
                """{"eventType":"x","timestamp":"t"}""",
            ),
        )
    }

    @Test
    fun `Notification round-trips and defaults its delivery state`() {
        val notification = json.decodeFromString(
            Notification.serializer(),
            """{"id":"n-1","userId":"user-1","type":"file_shared","title":"t","message":"m","createdAt":"2024-01-01T00:00:00Z"}""",
        )

        assertFalse(notification.read)
        assertEquals(emptyList(), notification.deliveredVia)
        assertEquals("", notification.resourceId)

        val delivered = notification.copy(read = true, deliveredVia = listOf("in_app", "email"))
        val encoded = json.encodeToString(Notification.serializer(), delivered)

        assertTrue(encoded.contains("\"read\":true"), encoded)
        assertEquals(delivered, json.decodeFromString(Notification.serializer(), encoded))
    }

    @Test
    fun `NotificationPreference defaults each event type to its documented channels`() {
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

        val encoded = json.encodeToString(NotificationPreference.serializer(), preference)
        assertEquals(preference, json.decodeFromString(NotificationPreference.serializer(), encoded))
    }

    @Test
    fun `DeliveryChannel serializes by name`() {
        assertEquals("\"PUSH\"", json.encodeToString(DeliveryChannel.serializer(), DeliveryChannel.PUSH))
        assertEquals(
            DeliveryChannel.EMAIL,
            json.decodeFromString(DeliveryChannel.serializer(), "\"EMAIL\""),
        )
        assertEquals(3, DeliveryChannel.entries.size)
    }

    @Test
    fun `PaginatedResponse carries the paging metadata`() {
        val page = PaginatedResponse(
            data = listOf(
                Notification(
                    id = "n-1",
                    userId = "user-1",
                    type = "file_shared",
                    title = "t",
                    message = "m",
                    createdAt = "2024-01-01T00:00:00Z",
                )
            ),
            total = 42,
            page = 2,
            pageSize = 1,
            hasMore = true,
        )

        val serializer = PaginatedResponse.serializer(Notification.serializer())
        val encoded = json.encodeToString(serializer, page)

        assertTrue(encoded.contains("\"total\":42"), encoded)
        assertTrue(encoded.contains("\"hasMore\":true"), encoded)
        assertEquals(page, json.decodeFromString(serializer, encoded))
    }

    @Test
    fun `UnreadCountResponse and NotificationPreferenceRequest round-trip`() {
        val unread = UnreadCountResponse(userId = "user-1", unreadCount = 3)
        assertEquals(
            unread,
            json.decodeFromString(
                UnreadCountResponse.serializer(),
                json.encodeToString(UnreadCountResponse.serializer(), unread),
            ),
        )

        val request = json.decodeFromString(
            NotificationPreferenceRequest.serializer(),
            """{"userId":"user-1","eventType":"file_shared","channels":["EMAIL","PUSH"]}""",
        )
        assertEquals("user-1", request.userId)
        assertEquals("file_shared", request.eventType)
        assertEquals(listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH), request.channels)
    }

    /**
     * The API payloads are compared by value all over the service (deduplication, assertions on
     * responses), so their equality must be structural and must not match unrelated types.
     */
    @Test
    fun `the payload models compare by value`() {
        val notification = Notification(
            id = "n-1",
            userId = "user-1",
            type = "file_shared",
            title = "t",
            message = "m",
            createdAt = "2024-01-01T00:00:00Z",
        )
        val event = NotificationEvent(eventType = "file_shared", userId = "user-1", timestamp = "t")
        val sqsMessage = SqsNotificationMessage(eventType = "file_shared", timestamp = "t")
        val preference = NotificationPreference(
            userId = "user-1",
            channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL)),
        )
        val page = PaginatedResponse(listOf(notification), total = 1, page = 1, pageSize = 20, hasMore = false)
        val unread = UnreadCountResponse(userId = "user-1", unreadCount = 3)
        val request = NotificationPreferenceRequest(
            userId = "user-1",
            eventType = "file_shared",
            channels = listOf(DeliveryChannel.PUSH),
        )

        val samples = listOf<Any>(notification, event, sqsMessage, preference, page, unread, request)
        val copies = listOf<Any>(
            notification.copy(),
            event.copy(),
            sqsMessage.copy(),
            preference.copy(),
            page.copy(),
            unread.copy(),
            request.copy(),
        )
        val modified = listOf<Any>(
            notification.copy(id = "n-2"),
            event.copy(userId = "user-2"),
            sqsMessage.copy(eventType = "comment_added"),
            preference.copy(userId = "user-2"),
            page.copy(total = 2),
            unread.copy(unreadCount = 4),
            request.copy(channels = listOf(DeliveryChannel.EMAIL)),
        )

        samples.forEachIndexed { index, sample ->
            assertTrue(sample == sample, "$sample should equal itself")
            assertEquals(sample, copies[index])
            assertEquals(sample.hashCode(), copies[index].hashCode())
            assertFalse(sample == modified[index], "$sample should differ from ${modified[index]}")
            assertFalse(sample.equals("not a payload"), "$sample should not equal a String")
        }
    }
}
