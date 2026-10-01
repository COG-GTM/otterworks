package com.otterworks.notification.service

import com.otterworks.notification.model.SqsNotificationMessage
import com.otterworks.notification.template.NotificationTemplates
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class NotificationTemplatesTest {

    @Test
    fun `render file_shared event`() {
        val event = SqsNotificationMessage(
            eventType = "file_shared",
            fileId = "file-abc",
            ownerId = "alice",
            sharedWithUserId = "bob",
            timestamp = "2024-01-01T00:00:00Z",
        )

        val rendered = NotificationTemplates.render(event)

        assertEquals("File Shared With You", rendered.title)
        assertTrue(rendered.message.contains("alice"))
        assertEquals("OtterWorks: A file has been shared with you", rendered.emailSubject)
        assertTrue(rendered.emailBody.contains("file-abc"))
        assertTrue(rendered.emailBody.contains("alice"))
    }

    @Test
    fun `render comment_added event`() {
        val event = SqsNotificationMessage(
            eventType = "comment_added",
            actorId = "commenter-1",
            documentId = "doc-123",
            commentId = "c-1",
            userId = "owner-1",
            timestamp = "2024-01-01T00:00:00Z",
        )

        val rendered = NotificationTemplates.render(event)

        assertEquals("New Comment", rendered.title)
        assertTrue(rendered.message.contains("commenter-1"))
        assertTrue(rendered.message.contains("doc-123"))
    }

    @Test
    fun `render comment_resolved event`() {
        val event = SqsNotificationMessage(
            eventType = "comment_resolved",
            documentId = "doc-321",
            commentId = "comment-9",
            resolvedBy = "resolver-1",
            authorId = "author-1",
            timestamp = "2024-01-01T00:00:00Z",
        )

        val rendered = NotificationTemplates.render(event)

        assertEquals("Comment Resolved", rendered.title)
        assertTrue(rendered.message.contains("resolver-1"))
        assertTrue(rendered.message.contains("doc-321"))
        assertEquals("OtterWorks: Your comment was resolved", rendered.emailSubject)
        assertTrue(rendered.emailBody.contains("comment-9"))
        assertTrue(rendered.emailBody.contains("resolver-1"))
    }

    @Test
    fun `render document_edited event`() {
        val event = SqsNotificationMessage(
            eventType = "document_edited",
            actorId = "editor-1",
            documentId = "doc-456",
            userId = "owner-1",
            timestamp = "2024-01-01T00:00:00Z",
        )

        val rendered = NotificationTemplates.render(event)

        assertEquals("Document Edited", rendered.title)
        assertTrue(rendered.message.contains("editor-1"))
        assertTrue(rendered.message.contains("doc-456"))
    }

    @Test
    fun `render user_mentioned event`() {
        val event = SqsNotificationMessage(
            eventType = "user_mentioned",
            actorId = "mentioner-1",
            documentId = "doc-789",
            mentionedUserId = "mentioned-user",
            timestamp = "2024-01-01T00:00:00Z",
        )

        val rendered = NotificationTemplates.render(event)

        assertEquals("You Were Mentioned", rendered.title)
        assertTrue(rendered.message.contains("mentioner-1"))
        assertTrue(rendered.message.contains("doc-789"))
    }

    @Test
    fun `render unknown event type returns default`() {
        val event = SqsNotificationMessage(
            eventType = "unknown_event",
            timestamp = "2024-01-01T00:00:00Z",
        )

        val rendered = NotificationTemplates.render(event)

        assertEquals("Notification", rendered.title)
        assertEquals("You have a new notification.", rendered.message)
    }

    @Test
    fun `render uses ownerId as fallback for actorId`() {
        val event = SqsNotificationMessage(
            eventType = "file_shared",
            fileId = "file-xyz",
            ownerId = "fallback-owner",
            sharedWithUserId = "bob",
            actorId = "",
            timestamp = "2024-01-01T00:00:00Z",
        )

        val rendered = NotificationTemplates.render(event)

        assertTrue(rendered.message.contains("fallback-owner"))
    }
}
