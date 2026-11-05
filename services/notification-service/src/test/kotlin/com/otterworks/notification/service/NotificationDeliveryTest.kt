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
import kotlin.test.assertTrue

class NotificationDeliveryTest {

    private val repository = mockk<NotificationRepository>(relaxed = true)
    private val emailSender = mockk<EmailSender>(relaxed = true)
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)
    private val meterRegistry = SimpleMeterRegistry()

    private val service = NotificationService(repository, emailSender, webSocketManager, meterRegistry)

    private fun prefs(userId: String, vararg entries: Pair<String, List<DeliveryChannel>>) =
        NotificationPreference(userId = userId, channels = mapOf(*entries))

    // processEvent keeps appending to the same deliveredVia list after the first save, so
    // snapshot each saved notification at call time instead of capturing the live object.
    private val saved = mutableListOf<Notification>()

    init {
        coEvery { repository.saveNotification(any()) } answers {
            val n = firstArg<Notification>()
            saved += n.copy(deliveredVia = n.deliveredVia.toList())
        }
    }

    private fun savedNotifications(): List<Notification> {
        coVerify(atLeast = 1) { repository.saveNotification(any()) }
        return saved.toList()
    }

    private fun counter(name: String) = meterRegistry.counter(name).count()

    private val fileShared = SqsNotificationMessage(
        eventType = "file_shared",
        fileId = "file-1",
        ownerId = "owner-1",
        sharedWithUserId = "user-1",
        timestamp = "2024-01-01T00:00:00Z",
    )

    // --- routing: target user / resource resolution fallbacks ---

    @Test
    fun `comment_added falls back to ownerId when userId is blank`() {
        val event = SqsNotificationMessage(eventType = "comment_added", ownerId = "owner-9", timestamp = "t")
        assertEquals("owner-9", NotificationService.resolveTargetUserId(event))
    }

    @Test
    fun `document_edited falls back to ownerId when userId is blank`() {
        val event = SqsNotificationMessage(eventType = "document_edited", ownerId = "owner-9", timestamp = "t")
        assertEquals("owner-9", NotificationService.resolveTargetUserId(event))
    }

    @Test
    fun `user_mentioned falls back to userId when mentionedUserId is blank`() {
        val event = SqsNotificationMessage(eventType = "user_mentioned", userId = "user-7", timestamp = "t")
        assertEquals("user-7", NotificationService.resolveTargetUserId(event))
    }

    @Test
    fun `unknown event types route to userId`() {
        val event = SqsNotificationMessage(eventType = "something_else", userId = "user-5", ownerId = "o", timestamp = "t")
        assertEquals("user-5", NotificationService.resolveTargetUserId(event))
    }

    @Test
    fun `comment_added resource falls back to documentId when commentId is blank`() {
        val event = SqsNotificationMessage(eventType = "comment_added", documentId = "doc-3", timestamp = "t")
        assertEquals("doc-3", NotificationService.resolveResourceId(event))
    }

    @Test
    fun `user_mentioned resource is the documentId and unknown events have none`() {
        assertEquals(
            "doc-4",
            NotificationService.resolveResourceId(
                SqsNotificationMessage(eventType = "user_mentioned", documentId = "doc-4", timestamp = "t"),
            ),
        )
        assertEquals(
            "",
            NotificationService.resolveResourceId(
                SqsNotificationMessage(eventType = "other", documentId = "doc-4", fileId = "f", timestamp = "t"),
            ),
        )
    }

    // --- delivery: channel selection ---

    @Test
    fun `delivers on every channel for file_shared with default preferences`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns NotificationPreference(userId = "user-1")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true
        coEvery { webSocketManager.pushNotification("user-1", any()) } returns 2

        service.processEvent(fileShared)

        val saved = savedNotifications()
        assertEquals(2, saved.size, "notification is persisted, then re-saved with push status")
        assertEquals(listOf("in_app", "email"), saved.first().deliveredVia)
        assertEquals(listOf("in_app", "email", "push"), saved.last().deliveredVia)
        assertEquals(saved.first().id, saved.last().id)
        assertEquals(1.0, counter("notifications.processed"))
        assertEquals(1.0, counter("notifications.email.sent"))
        assertEquals(1.0, counter("notifications.push.sent"))
    }

    @Test
    fun `email is addressed to the target user with the rendered subject`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns
            prefs("user-1", "file_shared" to listOf(DeliveryChannel.EMAIL))
        val to = slot<String>()
        val subject = slot<String>()
        val body = slot<String>()
        coEvery { emailSender.sendEmail(capture(to), capture(subject), capture(body)) } returns true

        service.processEvent(fileShared)

        assertEquals("user-1@otterworks.io", to.captured)
        assertTrue(subject.captured.isNotBlank())
        assertTrue(body.captured.isNotBlank())
        assertEquals(listOf("email"), savedNotifications().single().deliveredVia)
    }

    @Test
    fun `failed email is not recorded as delivered`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns
            prefs("user-1", "file_shared" to listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP))
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns false

        service.processEvent(fileShared)

        assertEquals(listOf("in_app"), savedNotifications().single().deliveredVia)
        assertEquals(0.0, counter("notifications.email.sent"))
        assertEquals(1.0, counter("notifications.processed"))
    }

    @Test
    fun `push to a user with no open sockets is not recorded and does not re-save`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns
            prefs("user-1", "file_shared" to listOf(DeliveryChannel.IN_APP, DeliveryChannel.PUSH))
        coEvery { webSocketManager.pushNotification("user-1", any()) } returns 0

        service.processEvent(fileShared)

        coVerify(exactly = 1) { repository.saveNotification(any()) }
        assertEquals(listOf("in_app"), savedNotifications().single().deliveredVia)
        assertEquals(0.0, counter("notifications.push.sent"))
    }

    @Test
    fun `push is attempted only after the notification is persisted`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns
            prefs("user-1", "file_shared" to listOf(DeliveryChannel.PUSH))
        coEvery { webSocketManager.pushNotification("user-1", any()) } returns 1

        service.processEvent(fileShared)

        io.mockk.coVerifyOrder {
            repository.saveNotification(any())
            webSocketManager.pushNotification("user-1", any())
            repository.saveNotification(any())
        }
        assertEquals(listOf(emptyList(), listOf("push")), savedNotifications().map { it.deliveredVia })
    }

    @Test
    fun `disabled channels are skipped entirely`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns prefs("user-1", "file_shared" to emptyList())

        service.processEvent(fileShared)

        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
        coVerify(exactly = 0) { webSocketManager.pushNotification(any(), any()) }
        assertEquals(emptyList<String>(), savedNotifications().single().deliveredVia)
    }

    @Test
    fun `missing preference for the event type falls back to the default channels`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns
            prefs("user-1", "comment_added" to listOf(DeliveryChannel.IN_APP))
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true
        coEvery { webSocketManager.pushNotification(any(), any()) } returns 1

        service.processEvent(fileShared)

        coVerify(exactly = 1) { emailSender.sendEmail(any(), any(), any()) }
        coVerify(exactly = 1) { webSocketManager.pushNotification("user-1", any()) }
    }

    @Test
    fun `unknown event types fall back to in-app only`() = runTest {
        val event = SqsNotificationMessage(eventType = "folder_archived", userId = "user-2", timestamp = "t")
        coEvery { repository.getPreferences("user-2") } returns NotificationPreference(userId = "user-2")

        service.processEvent(event)

        coVerify(exactly = 0) { emailSender.sendEmail(any(), any(), any()) }
        coVerify(exactly = 0) { webSocketManager.pushNotification(any(), any()) }
        val saved = savedNotifications().single()
        assertEquals(listOf("in_app"), saved.deliveredVia)
        assertEquals("unknown", saved.resourceType)
        assertEquals("", saved.resourceId)
    }

    // --- persisted notification fields ---

    @Test
    fun `stored notification carries routing fields and is unread`() = runTest {
        val event = SqsNotificationMessage(
            eventType = "comment_added",
            userId = "doc-owner",
            actorId = "commenter",
            documentId = "doc-1",
            commentId = "c-1",
            timestamp = "2024-01-01T00:00:00Z",
        )
        coEvery { repository.getPreferences("doc-owner") } returns
            prefs("doc-owner", "comment_added" to listOf(DeliveryChannel.IN_APP))

        service.processEvent(event)

        val saved = savedNotifications().single()
        assertEquals("doc-owner", saved.userId)
        assertEquals("comment_added", saved.type)
        assertEquals("c-1", saved.resourceId)
        assertEquals("comment", saved.resourceType)
        assertEquals("commenter", saved.actorId)
        assertFalse(saved.read)
        assertTrue(saved.id.isNotBlank())
        assertTrue(saved.createdAt.isNotBlank())
        assertTrue(saved.title.isNotBlank())
    }

    @Test
    fun `actorId falls back to ownerId when the event has no actor`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns
            prefs("user-1", "file_shared" to listOf(DeliveryChannel.IN_APP))

        service.processEvent(fileShared)

        assertEquals("owner-1", savedNotifications().single().actorId)
    }

    @Test
    fun `blank target user skips preference lookup and metrics`() = runTest {
        service.processEvent(fileShared.copy(sharedWithUserId = ""))

        coVerify(exactly = 0) { repository.getPreferences(any()) }
        assertEquals(0.0, counter("notifications.processed"))
    }

    @Test
    fun `works without a meter registry`() = runTest {
        val noMetrics = NotificationService(repository, emailSender, webSocketManager, null)
        coEvery { repository.getPreferences("user-1") } returns NotificationPreference(userId = "user-1")
        coEvery { emailSender.sendEmail(any(), any(), any()) } returns true
        coEvery { webSocketManager.pushNotification(any(), any()) } returns 1

        noMetrics.processEvent(fileShared)

        coVerify(exactly = 2) { repository.saveNotification(any()) }
    }

    // --- preferences and passthroughs ---

    @Test
    fun `updatePreferences replaces only the given event type`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns NotificationPreference(userId = "user-1")
        val saved = slot<NotificationPreference>()
        coEvery { repository.savePreferences(capture(saved)) } returns Unit

        service.updatePreferences("user-1", "document_edited", listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH))

        val defaults = NotificationPreference(userId = "user-1").channels
        assertEquals("user-1", saved.captured.userId)
        assertEquals(listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH), saved.captured.channels["document_edited"])
        assertEquals(defaults - "document_edited", saved.captured.channels - "document_edited")
    }

    @Test
    fun `updatePreferences can add a new event type`() = runTest {
        coEvery { repository.getPreferences("user-1") } returns prefs("user-1")
        val saved = slot<NotificationPreference>()
        coEvery { repository.savePreferences(capture(saved)) } returns Unit

        service.updatePreferences("user-1", "custom_event", listOf(DeliveryChannel.IN_APP))

        assertEquals(mapOf("custom_event" to listOf(DeliveryChannel.IN_APP)), saved.captured.channels)
    }

    @Test
    fun `read, delete and preference lookups delegate to the repository`() = runTest {
        val n = Notification(id = "n-1", userId = "u", type = "file_shared", title = "t", message = "m", createdAt = "c")
        coEvery { repository.getNotificationById("n-1") } returns n
        coEvery { repository.getNotificationById("missing") } returns null
        coEvery { repository.deleteNotification("n-1") } returns true
        coEvery { repository.getPreferences("u") } returns prefs("u")

        assertEquals(n, service.getNotificationById("n-1"))
        assertEquals(null, service.getNotificationById("missing"))
        assertTrue(service.deleteNotification("n-1"))
        assertEquals(prefs("u"), service.getPreferences("u"))
    }
}
