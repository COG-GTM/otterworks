package com.otterworks.notification.routes

import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.configurePlugins
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.plugins.configureMonitoring
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.server.application.Application
import io.ktor.server.application.install
import io.ktor.server.testing.ApplicationTestBuilder
import io.ktor.server.testing.testApplication
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class RoutesTest {

    private val notificationService = mockk<NotificationService>(relaxed = true)
    private val webSocketManager = WebSocketManager()

    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "http://localhost:4566/000000000000/test-queue",
        snsTopicArn = "arn:aws:sns:us-east-1:000000000000:test-topic",
        dynamoDbTableNotifications = "test-notifications",
        dynamoDbTablePreferences = "test-preferences",
        sesFromEmail = "test@otterworks.io",
        sqsPollIntervalMs = 1000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )

    private val notification = Notification(
        id = "n-1",
        userId = "user-1",
        type = "file_shared",
        title = "File Shared With You",
        message = "A file has been shared with you.",
        resourceId = "file-1",
        resourceType = "file",
        actorId = "actor-1",
        read = false,
        deliveredVia = listOf("in_app"),
        createdAt = "2024-01-01T00:00:00Z",
    )

    @AfterTest
    fun tearDown() {
        org.koin.core.context.stopKoin()
    }

    private fun Application.testModule() {
        val registry = configureMonitoring()
        configurePlugins(config)
        install(Koin) {
            modules(
                module {
                    single { notificationService }
                    single { webSocketManager }
                },
            )
        }
        configureRouting(registry)
    }

    private fun withRoutes(block: suspend ApplicationTestBuilder.() -> Unit) = testApplication {
        application { testModule() }
        block()
    }

    @Test
    fun `health endpoint reports the service name`() = withRoutes {
        val response = client.get("/health")

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("""{"status":"healthy","service":"notification-service"}""", response.bodyAsText())
    }

    @Test
    fun `metrics endpoint exposes the prometheus scrape`() = withRoutes {
        val response = client.get("/metrics")

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("jvm_memory_used_bytes"))
    }

    @Test
    fun `listing notifications paginates using the user header`() = withRoutes {
        coEvery { notificationService.getNotifications("user-1", 2, 1) } returns Pair(listOf(notification), 5)

        val response = client.get("/api/v1/notifications?page=2&page_size=1") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        val body = response.bodyAsText()
        assertTrue(body.contains("\"total\":5"))
        assertTrue(body.contains("\"hasMore\":true"))
        assertTrue(body.contains("\"id\":\"n-1\""))
    }

    @Test
    fun `listing notifications accepts the user id as a query parameter and defaults the paging`() = withRoutes {
        coEvery { notificationService.getNotifications("user-2", 1, 20) } returns Pair(emptyList(), 0)

        val response = client.get("/api/v1/notifications?user_id=user-2")

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("\"hasMore\":false"))
        coVerify { notificationService.getNotifications("user-2", 1, 20) }
    }

    @Test
    fun `listing notifications rejects a request without a user id`() = withRoutes {
        val response = client.get("/api/v1/notifications")

        assertEquals(HttpStatusCode.BadRequest, response.status)
        assertTrue(response.bodyAsText().contains("user_id is required"))
    }

    @Test
    fun `unread count is returned for the requested user`() = withRoutes {
        coEvery { notificationService.getUnreadCount("user-1") } returns 7

        val response = client.get("/api/v1/notifications/unread-count") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("""{"userId":"user-1","unreadCount":7}""", response.bodyAsText())
    }

    @Test
    fun `unread count requires a user id`() = withRoutes {
        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/notifications/unread-count").status)
    }

    @Test
    fun `fetching a notification by id returns it when it exists`() = withRoutes {
        coEvery { notificationService.getNotificationById("n-1") } returns notification

        val response = client.get("/api/v1/notifications/n-1")

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("\"title\":\"File Shared With You\""))
    }

    @Test
    fun `fetching an unknown notification returns 404`() = withRoutes {
        coEvery { notificationService.getNotificationById("missing") } returns null

        val response = client.get("/api/v1/notifications/missing")

        assertEquals(HttpStatusCode.NotFound, response.status)
        assertTrue(response.bodyAsText().contains("Notification not found"))
    }

    @Test
    fun `marking a notification as read returns 204 and 404 when it is unknown`() = withRoutes {
        coEvery { notificationService.markAsRead("n-1") } returns true
        coEvery { notificationService.markAsRead("missing") } returns false

        assertEquals(HttpStatusCode.NoContent, client.put("/api/v1/notifications/n-1/read").status)
        assertEquals(HttpStatusCode.NotFound, client.put("/api/v1/notifications/missing/read").status)
    }

    @Test
    fun `marking all as read reports how many were updated`() = withRoutes {
        coEvery { notificationService.markAllAsRead("user-1") } returns 4

        val response = client.put("/api/v1/notifications/read-all") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("""{"markedCount":4}""", response.bodyAsText())
    }

    @Test
    fun `marking all as read requires a user id`() = withRoutes {
        assertEquals(HttpStatusCode.BadRequest, client.put("/api/v1/notifications/read-all").status)
    }

    @Test
    fun `deleting a notification returns 204 and 404 when it is unknown`() = withRoutes {
        coEvery { notificationService.deleteNotification("n-1") } returns true
        coEvery { notificationService.deleteNotification("missing") } returns false

        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/n-1").status)
        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/missing").status)
    }

    @Test
    fun `preferences are returned for the requested user`() = withRoutes {
        coEvery { notificationService.getPreferences("user-1") } returns NotificationPreference(
            userId = "user-1",
            channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL)),
        )

        val response = client.get("/api/v1/preferences?user_id=user-1")

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("\"file_shared\":[\"EMAIL\"]"))
    }

    @Test
    fun `preferences require a user id`() = withRoutes {
        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/preferences").status)
    }

    @Test
    fun `updating preferences forwards the requested channels to the service`() = withRoutes {
        val response = client.put("/api/v1/preferences") {
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"user-1","eventType":"file_shared","channels":["EMAIL","IN_APP"]}""")
        }

        assertEquals(HttpStatusCode.NoContent, response.status)
        coVerify {
            notificationService.updatePreferences(
                "user-1",
                "file_shared",
                listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP),
            )
        }
    }

    @Test
    fun `an unhandled failure is mapped to a 500 error payload`() = withRoutes {
        coEvery { notificationService.getUnreadCount("user-1") } throws RuntimeException("dynamo down")

        val response = client.get("/api/v1/notifications/unread-count") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.InternalServerError, response.status)
        assertTrue(response.bodyAsText().contains("Internal server error"))
    }
}
