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
import kotlin.test.assertTrue

/**
 * Covers the delivery bookkeeping of [NotificationService] — metrics, channel fallbacks and the
 * thin repository delegates — that [NotificationServiceTest] does not exercise.
 */
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

    private fun event(type: String) = SqsNotificationMessage(
        eventType = type,
        fileId = "file-1",
        ownerId = "owner-1",
        sharedWithUserId = "user-2",
        documentId = "doc-1",
        commentId = "comment-1",
        userId = "user-1",
        actorId = "actor-1",
        mentionedUserId = "user-3",
        timestamp = "2024-01-01T00:00:00Z",
    )

    @Test
    fun `processEvent counts every successful delivery channel`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns NotificationPreference(userId = "user-2")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true
        coEvery { webSocketManager.pushNotification(any(), any()) } returns 2
        val saved = mutableListOf<Notification>()
        coEvery { repository.saveNotification(capture(saved)) } returns Unit

        service.processEvent(event("file_shared"))

        assertEquals(1.0, meterRegistry.counter("notifications.processed").count())
        assertEquals(1.0, meterRegistry.counter("notifications.email.sent").count())
        assertEquals(1.0, meterRegistry.counter("notifications.push.sent").count())
        // The notification is stored once before the push and once after it succeeds. Both copies
        // share the same mutable deliveredVia list, so the captured first save reads back as the
        // final channel list too.
        assertEquals(2, saved.size)
        assertEquals(listOf("in_app", "email", "push"), saved[1].deliveredVia)
        assertEquals(saved[0].id, saved[1].id)
        coVerify { emailSender.sendEmail("user-2@otterworks.io", any(), any()) }
    }

    @Test
    fun `processEvent does not record email delivery when sending fails`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns NotificationPreference(userId = "user-2")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns false
        coEvery { webSocketManager.pushNotification(any(), any()) } returns 0
        val saved = slot<Notification>()
        coEvery { repository.saveNotification(capture(saved)) } returns Unit

        service.processEvent(event("file_shared"))

        assertEquals(listOf("in_app"), saved.captured.deliveredVia)
        assertEquals(0.0, meterRegistry.counter("notifications.email.sent").count())
        assertEquals(0.0, meterRegistry.counter("notifications.push.sent").count())
        assertEquals(1.0, meterRegistry.counter("notifications.processed").count())
        coVerify(exactly = 1) { repository.saveNotification(any()) }
    }

    @Test
    fun `processEvent falls back to in-app delivery for an unconfigured event type`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns
            NotificationPreference(userId = "user-1", channels = emptyMap())
        val saved = slot<Notification>()
        coEvery { repository.saveNotification(capture(saved)) } returns Unit

        service.processEvent(event("workspace_archived"))

        val notification = saved.captured
        assertEquals("workspace_archived", notification.type)
        assertEquals("", notification.resourceId)
        assertEquals("unknown", notification.resourceType)
        assertEquals("Notification", notification.title)
        assertEquals(listOf("in_app"), notification.deliveredVia)
        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
        coVerify(exactly = 0) { webSocketManager.pushNotification(any(), any()) }
    }

    @Test
    fun `processEvent uses the default channels of a known type when preferences are empty`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns
            NotificationPreference(userId = "user-1", channels = emptyMap())
        coEvery { webSocketManager.pushNotification(any(), any()) } returns 1
        val saved = mutableListOf<Notification>()
        coEvery { repository.saveNotification(capture(saved)) } returns Unit

        service.processEvent(event("comment_added"))

        assertEquals(listOf("in_app", "push"), saved.last().deliveredVia)
        assertEquals("comment-1", saved.last().resourceId)
        assertEquals("comment", saved.last().resourceType)
        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
    }

    @Test
    fun `processEvent falls back to the owner as actor`() = runTest {
        coEvery { repository.getPreferences("user-2") } returns
            NotificationPreference(userId = "user-2", channels = mapOf("file_shared" to emptyList()))
        val saved = slot<Notification>()
        coEvery { repository.saveNotification(capture(saved)) } returns Unit

        service.processEvent(event("file_shared").copy(actorId = ""))

        assertEquals("owner-1", saved.captured.actorId)
        assertEquals(emptyList(), saved.captured.deliveredVia)
    }

    @Test
    fun `getNotificationById delegates to the repository`() = runTest {
        val stored = Notification(
            id = "notif-1",
            userId = "user-1",
            type = "file_shared",
            title = "File Shared",
            message = "A file has been shared with you.",
            createdAt = "2024-01-01T00:00:00Z",
        )
        coEvery { repository.getNotificationById("notif-1") } returns stored

        assertEquals(stored, service.getNotificationById("notif-1"))
    }

    @Test
    fun `deleteNotification delegates to the repository`() = runTest {
        coEvery { repository.deleteNotification("notif-1") } returns true

        assertTrue(service.deleteNotification("notif-1"))
        coVerify { repository.deleteNotification("notif-1") }
    }

    @Test
    fun `getPreferences delegates to the repository`() = runTest {
        val preferences = NotificationPreference(userId = "user-1")
        coEvery { repository.getPreferences("user-1") } returns preferences

        assertEquals(preferences, service.getPreferences("user-1"))
    }

    @Test
    fun `updatePreferences merges the new channels into the stored preferences`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns NotificationPreference(
            userId = "user-1",
            channels = mapOf("comment_added" to listOf(DeliveryChannel.IN_APP)),
        )
        val saved = slot<NotificationPreference>()
        coEvery { repository.savePreferences(capture(saved)) } returns Unit

        service.updatePreferences("user-1", "file_shared", listOf(DeliveryChannel.EMAIL))

        assertEquals("user-1", saved.captured.userId)
        assertEquals(listOf(DeliveryChannel.IN_APP), saved.captured.channels["comment_added"])
        assertEquals(listOf(DeliveryChannel.EMAIL), saved.captured.channels["file_shared"])
    }

    @Test
    fun `resolvers fall back for events that omit the primary identifier`() {
        assertEquals("owner-1", NotificationService.resolveTargetUserId(
            event("comment_added").copy(userId = "")
        ))
        assertEquals("owner-1", NotificationService.resolveTargetUserId(
            event("document_edited").copy(userId = "")
        ))
        assertEquals("user-1", NotificationService.resolveTargetUserId(
            event("user_mentioned").copy(mentionedUserId = "")
        ))
        assertEquals("user-1", NotificationService.resolveTargetUserId(event("workspace_archived")))

        assertEquals("doc-1", NotificationService.resolveResourceId(
            event("comment_added").copy(commentId = "")
        ))
        assertEquals("doc-1", NotificationService.resolveResourceId(event("user_mentioned")))
        assertEquals("", NotificationService.resolveResourceId(event("workspace_archived")))

        assertEquals("document", NotificationService.resolveResourceType(event("user_mentioned")))
        assertEquals("unknown", NotificationService.resolveResourceType(event("workspace_archived")))
    }
}
