package com.otterworks.notification.service

import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.model.SqsNotificationMessage
import com.otterworks.notification.repository.NotificationRepository
import com.otterworks.notification.template.NotificationTemplates
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
import kotlin.test.assertTrue

class NotificationServiceQaTest {

    private val repository = mockk<NotificationRepository>(relaxed = true)
    private val emailSender = mockk<EmailSender>(relaxed = true)
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)
    private val registry = SimpleMeterRegistry()
    private val service = NotificationService(repository, emailSender, webSocketManager, registry)

    private val share = SqsNotificationMessage(
        eventType = "file_shared", fileId = "f1", ownerId = "owner", sharedWithUserId = "recipient",
        timestamp = "2026-01-01T00:00:00Z",
    )

    @Test
    fun `share event targets the recipient, not the owner`() = runTest {
        coEvery { repository.getPreferences("recipient") } returns NotificationPreference("recipient")
        service.processEvent(share)
        val saved = slot<Notification>()
        coVerify { repository.saveNotification(capture(saved)) }
        assertEquals("recipient", saved.captured.userId)
        assertEquals("owner", saved.captured.actorId)
        assertEquals("f1", saved.captured.resourceId)
        assertEquals("file", saved.captured.resourceType)
        assertFalse(saved.captured.read)
        coVerify(exactly = 0) { repository.getPreferences("owner") }
    }

    @Test
    fun `failed email is not recorded as delivered`() = runTest {
        coEvery { repository.getPreferences(any()) } returns NotificationPreference("recipient")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns false
        service.processEvent(share)
        val saved = mutableListOf<Notification>()
        coVerify { repository.saveNotification(capture(saved)) }
        assertFalse("email" in saved.last().deliveredVia)
        assertEquals(0.0, registry.counter("notifications.email.sent").count())
    }

    @Test
    fun `email is addressed to the recipient`() = runTest {
        coEvery { repository.getPreferences(any()) } returns NotificationPreference("recipient")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true
        service.processEvent(share)
        coVerify { emailSender.sendEmail("recipient@otterworks.io", "OtterWorks: A file has been shared with you", any()) }
        assertEquals(1.0, registry.counter("notifications.email.sent").count())
        assertEquals(1.0, registry.counter("notifications.processed").count())
    }

    @Test
    fun `disabling all channels still stores the notification without delivery`() = runTest {
        coEvery { repository.getPreferences(any()) } returns
            NotificationPreference("recipient", mapOf("file_shared" to emptyList()))
        service.processEvent(share)
        val saved = slot<Notification>()
        coVerify(exactly = 1) { repository.saveNotification(capture(saved)) }
        assertTrue(saved.captured.deliveredVia.isEmpty())
        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
        coVerify(exactly = 0) { webSocketManager.pushNotification(any(), any()) }
    }

    @Test
    fun `unknown event type defaults to in-app delivery for userId`() = runTest {
        coEvery { repository.getPreferences("u9") } returns NotificationPreference("u9")
        service.processEvent(SqsNotificationMessage(eventType = "file_trashed", userId = "u9", timestamp = "t"))
        val saved = slot<Notification>()
        coVerify { repository.saveNotification(capture(saved)) }
        assertEquals(listOf("in_app"), saved.captured.deliveredVia)
        assertEquals("Notification", saved.captured.title)
        assertEquals("unknown", saved.captured.resourceType)
    }

    @Test
    fun `push delivery re-saves with push recorded only when a session received it`() = runTest {
        coEvery { repository.getPreferences(any()) } returns NotificationPreference("recipient")
        coEvery { webSocketManager.pushNotification("recipient", any()) } returns 0
        service.processEvent(share)
        coVerify(exactly = 1) { repository.saveNotification(any()) }
    }

    @Test
    fun `updatePreferences merges one event type into existing channels`() = runTest {
        coEvery { repository.getPreferences("u1") } returns NotificationPreference("u1")
        service.updatePreferences("u1", "document_edited", listOf(DeliveryChannel.EMAIL))
        val saved = slot<NotificationPreference>()
        coVerify { repository.savePreferences(capture(saved)) }
        assertEquals(listOf(DeliveryChannel.EMAIL), saved.captured.channels["document_edited"])
        assertEquals(
            NotificationPreference("u1").channels["file_shared"],
            saved.captured.channels["file_shared"],
        )
    }

    @Test
    fun `delete and getById delegate to the repository`() = runTest {
        coEvery { repository.deleteNotification("n1") } returns true
        coEvery { repository.getNotificationById("n1") } returns null
        assertTrue(service.deleteNotification("n1"))
        assertEquals(null, service.getNotificationById("n1"))
    }

    @Test
    fun `template variables from events are not re-interpolated`() {
        val rendered = NotificationTemplates.render(
            share.copy(actorId = "{{env:PATH}}")
        )
        assertTrue(rendered.message.contains("{{env:PATH}}"))
        assertFalse(rendered.emailBody.contains(System.getenv("PATH") ?: "\u0000never"))
    }
}
