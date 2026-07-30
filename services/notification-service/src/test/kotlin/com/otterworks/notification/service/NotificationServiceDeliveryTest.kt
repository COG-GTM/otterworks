package com.otterworks.notification.service

import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.model.SqsNotificationMessage
import com.otterworks.notification.notification
import com.otterworks.notification.repository.NotificationRepository
import com.otterworks.notification.websocket.WebSocketManager
import io.micrometer.core.instrument.simple.SimpleMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.coVerifyOrder
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Covers the delivery-channel bookkeeping and the metered paths of [NotificationService]. */
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

    private fun event(
        eventType: String = "file_shared",
        sharedWithUserId: String = "user-2",
    ) = SqsNotificationMessage(
        eventType = eventType,
        fileId = "file-1",
        ownerId = "owner-1",
        sharedWithUserId = sharedWithUserId,
        documentId = "doc-1",
        userId = "user-2",
        mentionedUserId = "user-2",
        timestamp = "2024-01-01T00:00:00Z",
    )

    private fun counter(name: String): Double =
        meterRegistry.find(name).counter()?.count() ?: 0.0

    @Test
    fun `a delivered push is recorded on the stored notification and metered`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns NotificationPreference(userId = "user-2")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true
        coEvery { webSocketManager.pushNotification(eq("user-2"), any()) } returns 2

        service.processEvent(event())

        val saved = mutableListOf<Notification>()
        coVerify(exactly = 2) { repository.saveNotification(capture(saved)) }
        coVerifyOrder {
            repository.saveNotification(any())
            webSocketManager.pushNotification("user-2", any())
            repository.saveNotification(any())
        }
        assertEquals(listOf("in_app", "email", "push"), saved.last().deliveredVia)
        assertEquals(saved.first().id, saved.last().id)
        assertEquals(1.0, counter("notifications.processed"))
        assertEquals(1.0, counter("notifications.email.sent"))
        assertEquals(1.0, counter("notifications.push.sent"))
    }

    @Test
    fun `a push with no live session leaves the stored notification untouched`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns NotificationPreference(userId = "user-2")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true
        coEvery { webSocketManager.pushNotification(eq("user-2"), any()) } returns 0

        service.processEvent(event())

        val saved = slot<Notification>()
        coVerify(exactly = 1) { repository.saveNotification(capture(saved)) }
        assertFalse(saved.captured.deliveredVia.contains("push"))
        assertEquals(0.0, counter("notifications.push.sent"))
    }

    @Test
    fun `a failed email is not recorded as a delivery channel`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns NotificationPreference(userId = "user-2")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns false
        coEvery { webSocketManager.pushNotification(eq("user-2"), any()) } returns 0

        service.processEvent(event())

        val saved = slot<Notification>()
        coVerify { repository.saveNotification(capture(saved)) }
        assertEquals(listOf("in_app"), saved.captured.deliveredVia)
        assertEquals(0.0, counter("notifications.email.sent"))
        assertEquals(1.0, counter("notifications.processed"))
    }

    @Test
    fun `an unknown event type falls back to in-app delivery only`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns NotificationPreference(
            userId = "user-2",
            channels = emptyMap(),
        )

        service.processEvent(event(eventType = "workflow_completed"))

        val saved = slot<Notification>()
        coVerify { repository.saveNotification(capture(saved)) }
        assertEquals(listOf("in_app"), saved.captured.deliveredVia)
        assertEquals("workflow_completed", saved.captured.type)
        assertEquals("Notification", saved.captured.title)
        assertEquals("", saved.captured.resourceId)
        assertEquals("unknown", saved.captured.resourceType)
        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
    }

    @Test
    fun `stored preferences override the defaults for the event type`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns NotificationPreference(
            userId = "user-2",
            channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL)),
        )
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true

        service.processEvent(event())

        val saved = slot<Notification>()
        coVerify { repository.saveNotification(capture(saved)) }
        assertEquals(listOf("email"), saved.captured.deliveredVia)
        coVerify(exactly = 0) { webSocketManager.pushNotification(any(), any()) }
    }

    @Test
    fun `the actor falls back to the file owner when the event carries no actor`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns NotificationPreference(
            userId = "user-2",
            channels = mapOf("file_shared" to listOf(DeliveryChannel.IN_APP)),
        )

        service.processEvent(event())

        val saved = slot<Notification>()
        coVerify { repository.saveNotification(capture(saved)) }
        assertEquals("owner-1", saved.captured.actorId)
        assertTrue(saved.captured.message.contains("owner-1"))
    }

    @Test
    fun `getNotificationById and deleteNotification delegate to the repository`() = runTest {
        coEvery { repository.getNotificationById("n-1") } returns notification(id = "n-1")
        coEvery { repository.getNotificationById("nope") } returns null
        coEvery { repository.deleteNotification("n-1") } returns true
        coEvery { repository.deleteNotification("nope") } returns false

        assertEquals("n-1", service.getNotificationById("n-1")?.id)
        assertNull(service.getNotificationById("nope"))
        assertTrue(service.deleteNotification("n-1"))
        assertFalse(service.deleteNotification("nope"))
    }

    @Test
    fun `getPreferences delegates to the repository`() = runTest {
        val stored = NotificationPreference(userId = "user-1", channels = emptyMap())
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

        service.updatePreferences("user-1", "comment_added", listOf(DeliveryChannel.PUSH))

        val saved = slot<NotificationPreference>()
        coVerify { repository.savePreferences(capture(saved)) }
        assertEquals("user-1", saved.captured.userId)
        assertEquals(listOf(DeliveryChannel.EMAIL), saved.captured.channels["file_shared"])
        assertEquals(listOf(DeliveryChannel.PUSH), saved.captured.channels["comment_added"])
    }

    @Test
    fun `updatePreferences adds channels for an event type that was never configured`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns NotificationPreference(
            userId = "user-1",
            channels = emptyMap(),
        )

        service.updatePreferences("user-1", "document_edited", listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH))

        val saved = slot<NotificationPreference>()
        coVerify { repository.savePreferences(capture(saved)) }
        assertEquals(
            listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH),
            saved.captured.channels["document_edited"],
        )
    }
}
