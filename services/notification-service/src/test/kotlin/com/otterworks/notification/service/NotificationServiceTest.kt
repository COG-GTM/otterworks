package com.otterworks.notification.service

import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.model.SqsNotificationMessage
import com.otterworks.notification.repository.NotificationRepository
import com.otterworks.notification.websocket.WebSocketManager
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class NotificationServiceTest {

    private val repository = mockk<NotificationRepository>(relaxed = true)
    private val emailSender = mockk<EmailSender>(relaxed = true)
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)

    private val service = NotificationService(
        repository = repository,
        emailSender = emailSender,
        webSocketManager = webSocketManager,
        meterRegistry = null,
    )

    @Test
    fun `resolveTargetUserId returns sharedWithUserId for file_shared events`() {
        val event = SqsNotificationMessage(
            eventType = "file_shared",
            fileId = "file-123",
            ownerId = "owner-1",
            sharedWithUserId = "user-2",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals("user-2", NotificationService.resolveTargetUserId(event))
    }

    @Test
    fun `resolveTargetUserId returns mentionedUserId for user_mentioned events`() {
        val event = SqsNotificationMessage(
            eventType = "user_mentioned",
            mentionedUserId = "mentioned-user",
            actorId = "actor-1",
            documentId = "doc-1",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals("mentioned-user", NotificationService.resolveTargetUserId(event))
    }

    @Test
    fun `resolveTargetUserId returns userId for comment_added events`() {
        val event = SqsNotificationMessage(
            eventType = "comment_added",
            userId = "doc-owner",
            actorId = "commenter",
            documentId = "doc-1",
            commentId = "comment-1",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals("doc-owner", NotificationService.resolveTargetUserId(event))
    }

    @Test
    fun `resolveTargetUserId returns comment author for comment_resolved events`() {
        val event = SqsNotificationMessage(
            eventType = "comment_resolved",
            userId = "comment-author",
            resolvedBy = "resolver-1",
            documentId = "doc-1",
            commentId = "comment-1",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals("comment-author", NotificationService.resolveTargetUserId(event))
    }

    @Test
    fun `resolveResourceId returns commentId for comment_resolved`() {
        val event = SqsNotificationMessage(
            eventType = "comment_resolved",
            commentId = "comment-xyz",
            documentId = "doc-1",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals("comment-xyz", NotificationService.resolveResourceId(event))
    }

    @Test
    fun `resolveResourceId falls back to documentId for comment_resolved`() {
        val event = SqsNotificationMessage(
            eventType = "comment_resolved",
            documentId = "doc-1",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals("doc-1", NotificationService.resolveResourceId(event))
    }

    @Test
    fun `resolveTargetUserId returns userId for document_edited events`() {
        val event = SqsNotificationMessage(
            eventType = "document_edited",
            userId = "doc-owner",
            actorId = "editor",
            documentId = "doc-1",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals("doc-owner", NotificationService.resolveTargetUserId(event))
    }

    @Test
    fun `resolveResourceId returns fileId for file_shared`() {
        val event = SqsNotificationMessage(
            eventType = "file_shared",
            fileId = "file-abc",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals("file-abc", NotificationService.resolveResourceId(event))
    }

    @Test
    fun `resolveResourceId returns commentId for comment_added`() {
        val event = SqsNotificationMessage(
            eventType = "comment_added",
            commentId = "comment-xyz",
            documentId = "doc-1",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals("comment-xyz", NotificationService.resolveResourceId(event))
    }

    @Test
    fun `resolveResourceId returns documentId for document_edited`() {
        val event = SqsNotificationMessage(
            eventType = "document_edited",
            documentId = "doc-123",
            timestamp = "2024-01-01T00:00:00Z",
        )
        assertEquals("doc-123", NotificationService.resolveResourceId(event))
    }

    @Test
    fun `resolveResourceType returns correct types`() {
        assertEquals("file", NotificationService.resolveResourceType(
            SqsNotificationMessage(eventType = "file_shared", timestamp = "2024-01-01T00:00:00Z")
        ))
        assertEquals("comment", NotificationService.resolveResourceType(
            SqsNotificationMessage(eventType = "comment_added", timestamp = "2024-01-01T00:00:00Z")
        ))
        assertEquals("document", NotificationService.resolveResourceType(
            SqsNotificationMessage(eventType = "document_edited", timestamp = "2024-01-01T00:00:00Z")
        ))
        assertEquals("document", NotificationService.resolveResourceType(
            SqsNotificationMessage(eventType = "user_mentioned", timestamp = "2024-01-01T00:00:00Z")
        ))
        assertEquals("comment", NotificationService.resolveResourceType(
            SqsNotificationMessage(eventType = "comment_resolved", timestamp = "2024-01-01T00:00:00Z")
        ))
        assertEquals("unknown", NotificationService.resolveResourceType(
            SqsNotificationMessage(eventType = "other_event", timestamp = "2024-01-01T00:00:00Z")
        ))
    }

    @Test
    fun `processEvent stores in-app notification and sends email for file_shared`() = runTest {
        val event = SqsNotificationMessage(
            eventType = "file_shared",
            fileId = "file-123",
            ownerId = "owner-1",
            sharedWithUserId = "user-2",
            timestamp = "2024-01-01T00:00:00Z",
        )

        coEvery { repository.getPreferences("user-2") } returns NotificationPreference(userId = "user-2")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true

        service.processEvent(event)

        val savedNotifications = mutableListOf<Notification>()
        coVerify(atLeast = 1) { repository.saveNotification(capture(savedNotifications)) }

        val lastSaved = savedNotifications.last()
        assertEquals("user-2", lastSaved.userId)
        assertEquals("file_shared", lastSaved.type)
        assertEquals("File Shared With You", lastSaved.title)
        assertTrue(lastSaved.deliveredVia.contains("in_app"))
    }

    @Test
    fun `processEvent skips email when not in preferences`() = runTest {
        val event = SqsNotificationMessage(
            eventType = "document_edited",
            userId = "user-1",
            actorId = "editor-1",
            documentId = "doc-1",
            timestamp = "2024-01-01T00:00:00Z",
        )

        val prefs = NotificationPreference(
            userId = "user-1",
            channels = mapOf("document_edited" to listOf(DeliveryChannel.IN_APP)),
        )
        coEvery { repository.getPreferences("user-1") } returns prefs

        service.processEvent(event)

        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
        coVerify(atLeast = 1) { repository.saveNotification(any()) }
    }

    @Test
    fun `processEvent does nothing for blank target user`() = runTest {
        val event = SqsNotificationMessage(
            eventType = "file_shared",
            fileId = "file-123",
            ownerId = "owner-1",
            sharedWithUserId = "",
            timestamp = "2024-01-01T00:00:00Z",
        )

        service.processEvent(event)

        coVerify(exactly = 0) { repository.saveNotification(any()) }
        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
    }

    @Test
    fun `getNotifications delegates to repository`() = runTest {
        val notifications = listOf(
            Notification(
                id = "n-1",
                userId = "user-1",
                type = "file_shared",
                title = "Test",
                message = "Test msg",
                createdAt = "2024-01-01T00:00:00Z",
            )
        )
        coEvery { repository.getNotificationsByUserId("user-1", 1, 20) } returns Pair(notifications, 1)

        val (result, total) = service.getNotifications("user-1", 1, 20)
        assertEquals(1, result.size)
        assertEquals(1, total)
        assertEquals("n-1", result[0].id)
    }

    @Test
    fun `markAsRead delegates to repository`() = runTest {
        coEvery { repository.markAsRead("n-1") } returns true
        assertTrue(service.markAsRead("n-1"))
    }

    @Test
    fun `markAllAsRead delegates to repository`() = runTest {
        coEvery { repository.markAllAsRead("user-1") } returns 5
        assertEquals(5, service.markAllAsRead("user-1"))
    }

    @Test
    fun `getUnreadCount delegates to repository`() = runTest {
        coEvery { repository.getUnreadCount("user-1") } returns 3
        assertEquals(3, service.getUnreadCount("user-1"))
    }

    @Test
    fun `processEvent notifies comment author for comment_resolved`() = runTest {
        val event = SqsNotificationMessage(
            eventType = "comment_resolved",
            userId = "comment-author",
            resolvedBy = "resolver-1",
            documentId = "doc-321",
            commentId = "c-9",
            timestamp = "2024-01-01T00:00:00Z",
        )

        coEvery { repository.getPreferences("comment-author") } returns
            NotificationPreference(userId = "comment-author")

        service.processEvent(event)

        val savedNotifications = mutableListOf<Notification>()
        coVerify(atLeast = 1) { repository.saveNotification(capture(savedNotifications)) }

        val lastSaved = savedNotifications.last()
        assertEquals("comment-author", lastSaved.userId)
        assertEquals("comment_resolved", lastSaved.type)
        assertEquals("Comment Resolved", lastSaved.title)
        assertEquals("c-9", lastSaved.resourceId)
        assertEquals("comment", lastSaved.resourceType)
        assertTrue(lastSaved.deliveredVia.contains("in_app"))
        assertTrue(lastSaved.message.contains("resolver-1"))
        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
        coVerify { webSocketManager.pushNotification("comment-author", any()) }
    }

    @Test
    fun `processEvent sends push notification when PUSH channel enabled`() = runTest {
        val event = SqsNotificationMessage(
            eventType = "user_mentioned",
            mentionedUserId = "user-3",
            actorId = "actor-1",
            documentId = "doc-1",
            timestamp = "2024-01-01T00:00:00Z",
        )

        coEvery { repository.getPreferences("user-3") } returns NotificationPreference(userId = "user-3")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true

        service.processEvent(event)

        coVerify { webSocketManager.pushNotification("user-3", any()) }
    }
}
