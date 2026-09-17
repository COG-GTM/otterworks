package com.otterworks.notification.service

import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.model.SqsNotificationMessage
import com.otterworks.notification.repository.NotificationRepository
import com.otterworks.notification.websocket.WebSocketManager
import io.micrometer.core.instrument.simple.SimpleMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Delivery-channel behaviour of [NotificationService.processEvent] plus its repository delegates. */
class NotificationServiceDeliveryTest {

    private val repository = mockk<NotificationRepository>(relaxed = true)
    private val emailSender = mockk<EmailSender>(relaxed = true)
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)
    private val meterRegistry = SimpleMeterRegistry()

    private val service = NotificationService(
        repository = repository,
        emailSender = emailSender,
        webSocketManager = webSocketManager,
        meterRegistry = meterRegistry,
    )

    private val fileShared = SqsNotificationMessage(
        eventType = "file_shared",
        fileId = "file-1",
        ownerId = "owner-1",
        sharedWithUserId = "user-2",
        timestamp = "2024-01-01T00:00:00Z",
    )

    private fun preferences(vararg channels: DeliveryChannel) = NotificationPreference(
        userId = "user-2",
        channels = mapOf("file_shared" to channels.toList()),
    )

    /** Snapshots the delivery state at save time; the service mutates one list across both saves. */
    private fun recordSaves(ids: MutableList<String>, channels: MutableList<List<String>>) {
        coEvery { repository.saveNotification(any()) } coAnswers {
            val notification = firstArg<Notification>()
            ids += notification.id
            channels += notification.deliveredVia.toList()
        }
    }

    @Test
    fun `a pushed notification is re-saved with the push delivery recorded`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns preferences(DeliveryChannel.PUSH)
        coEvery { webSocketManager.pushNotification("user-2", any()) } returns 2
        val ids = mutableListOf<String>()
        val channels = mutableListOf<List<String>>()
        recordSaves(ids, channels)

        service.processEvent(fileShared)

        assertEquals(2, ids.size)
        assertEquals(ids[0], ids[1])
        assertEquals(emptyList(), channels[0])
        assertEquals(listOf("push"), channels[1])
        assertEquals(1.0, meterRegistry.counter("notifications.push.sent").count())
        assertEquals(1.0, meterRegistry.counter("notifications.processed").count())
    }

    @Test
    fun `a service without a meter registry still records the push delivery`() = runTest {
        val unmetered = NotificationService(
            repository = repository,
            emailSender = emailSender,
            webSocketManager = webSocketManager,
            meterRegistry = null,
        )
        coEvery { repository.getPreferences("user-2") } returns preferences(DeliveryChannel.PUSH)
        coEvery { webSocketManager.pushNotification("user-2", any()) } returns 1
        val ids = mutableListOf<String>()
        val channels = mutableListOf<List<String>>()
        recordSaves(ids, channels)

        unmetered.processEvent(fileShared)

        assertEquals(listOf("push"), channels.last())
        assertEquals(0.0, meterRegistry.counter("notifications.push.sent").count())
    }

    @Test
    fun `a notification nobody is connected for is not re-saved as pushed`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns preferences(DeliveryChannel.PUSH)
        coEvery { webSocketManager.pushNotification("user-2", any()) } returns 0
        val ids = mutableListOf<String>()
        val channels = mutableListOf<List<String>>()
        recordSaves(ids, channels)

        service.processEvent(fileShared)

        assertEquals(1, ids.size)
        assertEquals(emptyList(), channels.single())
        assertEquals(0.0, meterRegistry.counter("notifications.push.sent").count())
    }

    @Test
    fun `email delivery is recorded only when SES accepts the message`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns preferences(DeliveryChannel.EMAIL)
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true
        val saved = slot<Notification>()
        coEvery { repository.saveNotification(capture(saved)) } returns Unit

        service.processEvent(fileShared)

        assertEquals(listOf("email"), saved.captured.deliveredVia)
        assertEquals(1.0, meterRegistry.counter("notifications.email.sent").count())
        coVerify(exactly = 1) {
            emailSender.sendEmail(
                "user-2@otterworks.io",
                "OtterWorks: A file has been shared with you",
                match { it.contains("file-1") && it.contains("owner-1") },
            )
        }
        coVerify(exactly = 0) { webSocketManager.pushNotification(any(), any()) }
    }

    @Test
    fun `a rejected email is not recorded as delivered`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns preferences(DeliveryChannel.EMAIL)
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns false
        val saved = slot<Notification>()
        coEvery { repository.saveNotification(capture(saved)) } returns Unit

        service.processEvent(fileShared)

        assertEquals(emptyList(), saved.captured.deliveredVia)
        assertEquals(0.0, meterRegistry.counter("notifications.email.sent").count())
    }

    @Test
    fun `stored preferences without the event type fall back to the defaults`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns
            NotificationPreference(userId = "user-2", channels = emptyMap())
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true
        coEvery { webSocketManager.pushNotification("user-2", any()) } returns 1
        val ids = mutableListOf<String>()
        val channels = mutableListOf<List<String>>()
        recordSaves(ids, channels)

        service.processEvent(fileShared)

        // The default preference for file_shared is EMAIL + IN_APP + PUSH.
        assertEquals(listOf("in_app", "email"), channels.first())
        assertEquals(listOf("in_app", "email", "push"), channels.last())
    }

    @Test
    fun `an unknown event type is delivered in-app only`() = runTest {
        val event = SqsNotificationMessage(
            eventType = "account_deleted",
            userId = "user-9",
            timestamp = "2024-01-01T00:00:00Z",
        )
        coEvery { repository.getPreferences("user-9") } returns
            NotificationPreference(userId = "user-9", channels = emptyMap())
        val saved = slot<Notification>()
        coEvery { repository.saveNotification(capture(saved)) } returns Unit

        service.processEvent(event)

        assertEquals(listOf("in_app"), saved.captured.deliveredVia)
        assertEquals("Notification", saved.captured.title)
        assertEquals("", saved.captured.resourceId)
        assertEquals("unknown", saved.captured.resourceType)
        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
        coVerify(exactly = 0) { webSocketManager.pushNotification(any(), any()) }
    }

    @Test
    fun `an event without a target user is dropped`() = runTest {
        service.processEvent(
            SqsNotificationMessage(eventType = "file_shared", timestamp = "2024-01-01T00:00:00Z")
        )

        coVerify(exactly = 0) { repository.getPreferences(any()) }
        coVerify(exactly = 0) { repository.saveNotification(any()) }
        assertEquals(0.0, meterRegistry.counter("notifications.processed").count())
    }

    @Test
    fun `the actor falls back to the owner when the event carries no actor`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns preferences()
        val saved = slot<Notification>()
        coEvery { repository.saveNotification(capture(saved)) } returns Unit

        service.processEvent(fileShared)

        assertEquals("owner-1", saved.captured.actorId)
        assertEquals("file-1", saved.captured.resourceId)
        assertEquals("file", saved.captured.resourceType)
        assertEquals("file_shared", saved.captured.type)
        assertFalse(saved.captured.read)
        assertEquals(emptyList(), saved.captured.deliveredVia)
    }

    @Test
    fun `resolveTargetUserId falls back for events that only carry an owner`() {
        val comment = SqsNotificationMessage(
            eventType = "comment_added",
            ownerId = "owner-1",
            documentId = "doc-1",
            timestamp = "t",
        )
        val edit = SqsNotificationMessage(
            eventType = "document_edited",
            ownerId = "owner-2",
            documentId = "doc-2",
            timestamp = "t",
        )
        val mention = SqsNotificationMessage(
            eventType = "user_mentioned",
            userId = "user-3",
            documentId = "doc-3",
            timestamp = "t",
        )
        val unknown = SqsNotificationMessage(eventType = "account_deleted", userId = "user-4", timestamp = "t")

        assertEquals("owner-1", NotificationService.resolveTargetUserId(comment))
        assertEquals("owner-2", NotificationService.resolveTargetUserId(edit))
        assertEquals("user-3", NotificationService.resolveTargetUserId(mention))
        assertEquals("user-4", NotificationService.resolveTargetUserId(unknown))
    }

    @Test
    fun `resolveResourceId prefers the comment id and falls back to the document`() {
        assertEquals(
            "c-1",
            NotificationService.resolveResourceId(
                SqsNotificationMessage(
                    eventType = "comment_added",
                    commentId = "c-1",
                    documentId = "doc-1",
                    timestamp = "t",
                )
            ),
        )
        assertEquals(
            "doc-1",
            NotificationService.resolveResourceId(
                SqsNotificationMessage(eventType = "comment_added", documentId = "doc-1", timestamp = "t")
            ),
        )
        assertEquals(
            "doc-2",
            NotificationService.resolveResourceId(
                SqsNotificationMessage(eventType = "user_mentioned", documentId = "doc-2", timestamp = "t")
            ),
        )
        assertEquals(
            "",
            NotificationService.resolveResourceId(
                SqsNotificationMessage(eventType = "account_deleted", timestamp = "t")
            ),
        )
    }

    @Test
    fun `resolveResourceType maps every known event type`() {
        fun typeOf(eventType: String) = NotificationService.resolveResourceType(
            SqsNotificationMessage(eventType = eventType, timestamp = "t")
        )

        assertEquals("file", typeOf("file_shared"))
        assertEquals("comment", typeOf("comment_added"))
        assertEquals("document", typeOf("document_edited"))
        assertEquals("document", typeOf("user_mentioned"))
        assertEquals("unknown", typeOf("account_deleted"))
    }

    @Test
    fun `read and delete operations delegate to the repository`() = runTest {
        coEvery { repository.deleteNotification("n-1") } returns true
        coEvery { repository.deleteNotification("missing") } returns false
        coEvery { repository.getNotificationById("n-1") } returns Notification(
            id = "n-1",
            userId = "user-1",
            type = "file_shared",
            title = "t",
            message = "m",
            createdAt = "2024-01-01T00:00:00Z",
        )
        coEvery { repository.getNotificationById("missing") } returns null

        assertTrue(service.deleteNotification("n-1"))
        assertFalse(service.deleteNotification("missing"))
        assertEquals("n-1", service.getNotificationById("n-1")?.id)
        assertNull(service.getNotificationById("missing"))
    }

    @Test
    fun `getPreferences delegates to the repository`() = runTest {
        val stored = NotificationPreference(
            userId = "user-1",
            channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL)),
        )
        coEvery { repository.getPreferences("user-1") } returns stored

        assertEquals(stored, service.getPreferences("user-1"))
    }

    @Test
    fun `updatePreferences replaces only the channels of the given event type`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns NotificationPreference(
            userId = "user-1",
            channels = mapOf(
                "file_shared" to listOf(DeliveryChannel.EMAIL),
                "comment_added" to listOf(DeliveryChannel.IN_APP),
            ),
        )
        val saved = slot<NotificationPreference>()
        coEvery { repository.savePreferences(capture(saved)) } returns Unit

        service.updatePreferences("user-1", "file_shared", listOf(DeliveryChannel.PUSH))

        assertEquals("user-1", saved.captured.userId)
        assertEquals(listOf(DeliveryChannel.PUSH), saved.captured.channels["file_shared"])
        assertEquals(listOf(DeliveryChannel.IN_APP), saved.captured.channels["comment_added"])
    }

    @Test
    fun `updatePreferences adds channels for an event type that had none`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns
            NotificationPreference(userId = "user-1", channels = emptyMap())
        val saved = slot<NotificationPreference>()
        coEvery { repository.savePreferences(capture(saved)) } returns Unit

        service.updatePreferences("user-1", "document_edited", listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP))

        assertEquals(
            mapOf("document_edited" to listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP)),
            saved.captured.channels,
        )
    }
}
