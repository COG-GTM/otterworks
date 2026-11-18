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
import kotlin.test.assertNull
import kotlin.test.assertTrue

class NotificationServiceDeliveryTest {

    private val repository = mockk<NotificationRepository>(relaxed = true)
    private val emailSender = mockk<EmailSender>(relaxed = true)
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)
    private val registry = SimpleMeterRegistry()
    private val service = NotificationService(repository, emailSender, webSocketManager, registry)

    private val mention = SqsNotificationMessage(
        eventType = "user_mentioned", mentionedUserId = "u3", actorId = "a1", documentId = "d1", timestamp = "t",
    )

    private fun count(name: String) = registry.counter(name).count()

    @Test
    fun `successful email and push are recorded and persisted`() = runTest {
        coEvery { repository.getPreferences("u3") } returns NotificationPreference("u3")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true
        coEvery { webSocketManager.pushNotification("u3", any()) } returns 2

        service.processEvent(mention)

        val saved = mutableListOf<Notification>()
        coVerify(exactly = 2) { repository.saveNotification(capture(saved)) }
        assertEquals(listOf("in_app", "email", "push"), saved.last().deliveredVia)
        assertEquals(saved.first().id, saved.last().id)
        assertEquals("d1", saved.last().resourceId)
        assertEquals("document", saved.last().resourceType)
        assertEquals("a1", saved.last().actorId)
        coVerify { emailSender.sendEmail("u3@otterworks.io", any(), any()) }
        assertEquals(1.0, count("notifications.email.sent"))
        assertEquals(1.0, count("notifications.push.sent"))
        assertEquals(1.0, count("notifications.processed"))
    }

    @Test
    fun `failed email and no live sockets leave only in-app`() = runTest {
        coEvery { repository.getPreferences("u3") } returns NotificationPreference("u3")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns false
        coEvery { webSocketManager.pushNotification("u3", any()) } returns 0

        service.processEvent(mention)

        val saved = slot<Notification>()
        coVerify(exactly = 1) { repository.saveNotification(capture(saved)) }
        assertEquals(listOf("in_app"), saved.captured.deliveredVia)
        assertEquals(0.0, count("notifications.email.sent"))
        assertEquals(0.0, count("notifications.push.sent"))
        assertEquals(1.0, count("notifications.processed"))
    }

    @Test
    fun `event type missing from stored preferences falls back to default channels`() = runTest {
        coEvery { repository.getPreferences("owner") } returns NotificationPreference("owner", channels = emptyMap())

        service.processEvent(
            SqsNotificationMessage(eventType = "comment_added", ownerId = "owner", documentId = "d1", timestamp = "t")
        )

        val saved = slot<Notification>()
        coVerify { repository.saveNotification(capture(saved)) }
        assertEquals("owner", saved.captured.userId)
        assertEquals("owner", saved.captured.actorId)
        assertEquals("d1", saved.captured.resourceId)
        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
        coVerify { webSocketManager.pushNotification("owner", any()) }
    }

    @Test
    fun `unknown event type defaults to in-app only`() = runTest {
        coEvery { repository.getPreferences("u1") } returns NotificationPreference("u1", channels = emptyMap())

        service.processEvent(SqsNotificationMessage(eventType = "custom", userId = "u1", timestamp = "t"))

        val saved = slot<Notification>()
        coVerify { repository.saveNotification(capture(saved)) }
        assertEquals(listOf("in_app"), saved.captured.deliveredVia)
        assertEquals("unknown", saved.captured.resourceType)
        assertEquals("Notification", saved.captured.title)
        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
        coVerify(exactly = 0) { webSocketManager.pushNotification(any(), any()) }
    }

    @Test
    fun `channels without in-app are not marked in_app`() = runTest {
        coEvery { repository.getPreferences("u1") } returns
            NotificationPreference("u1", channels = mapOf("document_edited" to listOf(DeliveryChannel.EMAIL)))
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true

        service.processEvent(SqsNotificationMessage(eventType = "document_edited", userId = "u1", documentId = "d", timestamp = "t"))

        val saved = slot<Notification>()
        coVerify { repository.saveNotification(capture(saved)) }
        assertEquals(listOf("email"), saved.captured.deliveredVia)
    }

    @Test
    fun `read and delete delegations`() = runTest {
        val n = Notification(id = "n1", userId = "u1", type = "x", title = "t", message = "m", createdAt = "c")
        coEvery { repository.getNotificationById("n1") } returns n
        coEvery { repository.getNotificationById("n2") } returns null
        coEvery { repository.deleteNotification("n1") } returns true
        coEvery { repository.getPreferences("u1") } returns NotificationPreference("u1")

        assertEquals(n, service.getNotificationById("n1"))
        assertNull(service.getNotificationById("n2"))
        assertTrue(service.deleteNotification("n1"))
        assertEquals(NotificationPreference("u1"), service.getPreferences("u1"))
    }

    @Test
    fun `updatePreferences merges a single event type into existing channels`() = runTest {
        coEvery { repository.getPreferences("u1") } returns NotificationPreference("u1")

        service.updatePreferences("u1", "file_shared", listOf(DeliveryChannel.PUSH))

        val saved = slot<NotificationPreference>()
        coVerify { repository.savePreferences(capture(saved)) }
        val expected = NotificationPreference("u1").channels.toMutableMap()
        expected["file_shared"] = listOf(DeliveryChannel.PUSH)
        assertEquals(expected, saved.captured.channels)
    }

    @Test
    fun `resolvers cover fallback fields`() {
        assertEquals("owner", NotificationService.resolveTargetUserId(SqsNotificationMessage(eventType = "document_edited", ownerId = "owner", timestamp = "t")))
        assertEquals("u1", NotificationService.resolveTargetUserId(SqsNotificationMessage(eventType = "user_mentioned", userId = "u1", timestamp = "t")))
        assertEquals("u9", NotificationService.resolveTargetUserId(SqsNotificationMessage(eventType = "other", userId = "u9", timestamp = "t")))
        assertEquals("d1", NotificationService.resolveResourceId(SqsNotificationMessage(eventType = "comment_added", documentId = "d1", timestamp = "t")))
        assertEquals("d2", NotificationService.resolveResourceId(SqsNotificationMessage(eventType = "user_mentioned", documentId = "d2", timestamp = "t")))
        assertEquals("", NotificationService.resolveResourceId(SqsNotificationMessage(eventType = "other", documentId = "d", timestamp = "t")))
    }
}
