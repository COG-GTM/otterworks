package com.otterworks.notification.routes

import com.otterworks.notification.configurePlugins
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.plugins.websocket.WebSockets as ClientWebSockets
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.server.testing.ApplicationTestBuilder
import io.ktor.server.testing.testApplication
import io.ktor.server.application.Application
import io.ktor.server.application.install
import io.ktor.websocket.CloseReason
import io.ktor.websocket.Frame
import io.ktor.websocket.close
import io.ktor.websocket.readText
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import org.koin.core.context.stopKoin
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
        sesFromEmail = "notifications@otterworks.io",
        sqsPollIntervalMs = 1000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    private fun notification(id: String) = Notification(
        id = id,
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

    private fun Application.notificationModule() {
        configurePlugins(config)
        install(Koin) {
            modules(
                module {
                    single { notificationService }
                    single { webSocketManager }
                }
            )
        }
        configureRouting(PrometheusMeterRegistry(PrometheusConfig.DEFAULT))
    }

    private fun ApplicationTestBuilder.installService() {
        application { notificationModule() }
    }

    @Test
    fun `health reports the service name`() = testApplication {
        installService()

        val response = client.get("/health")

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals(
            """{"status":"healthy","service":"notification-service"}""",
            response.bodyAsText(),
        )
    }

    @Test
    fun `metrics exposes the prometheus scrape`() = testApplication {
        installService()

        val response = client.get("/metrics")

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals(ContentType.Text.Plain, response.contentType()?.withoutParameters())
    }

    @Test
    fun `list notifications resolves the user from the header and paginates`() = testApplication {
        installService()
        coEvery { notificationService.getNotifications("user-1", 2, 5) } returns
            Pair(listOf(notification("notif-3")), 42)

        val response = client.get("/api/v1/notifications?page=2&page_size=5") {
            header("X-User-ID", "user-1")
        }

        assertEquals(HttpStatusCode.OK, response.status)
        val body = response.bodyAsText()
        assertTrue(body.contains("\"total\":42"))
        assertTrue(body.contains("\"page\":2"))
        assertTrue(body.contains("\"pageSize\":5"))
        assertTrue(body.contains("\"hasMore\":true"))
        assertTrue(body.contains("notif-3"))
    }

    @Test
    fun `list notifications falls back to the query parameter and default paging`() = testApplication {
        installService()
        coEvery { notificationService.getNotifications("user-2", 1, 20) } returns Pair(emptyList(), 0)

        val response = client.get("/api/v1/notifications?user_id=user-2&page=abc&page_size=xyz")

        assertEquals(HttpStatusCode.OK, response.status)
        val body = response.bodyAsText()
        assertTrue(body.contains("\"page\":1"))
        assertTrue(body.contains("\"pageSize\":20"))
        assertTrue(body.contains("\"hasMore\":false"))
    }

    @Test
    fun `list notifications rejects a missing user id`() = testApplication {
        installService()

        val response = client.get("/api/v1/notifications")

        assertEquals(HttpStatusCode.BadRequest, response.status)
        assertTrue(response.bodyAsText().contains("user_id is required"))
    }

    @Test
    fun `unread count returns the service value`() = testApplication {
        installService()
        coEvery { notificationService.getUnreadCount("user-1") } returns 7

        val response = client.get("/api/v1/notifications/unread-count") {
            header("X-User-ID", "user-1")
        }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("""{"userId":"user-1","unreadCount":7}""", response.bodyAsText())
    }

    @Test
    fun `unread count rejects a blank user id`() = testApplication {
        installService()

        val response = client.get("/api/v1/notifications/unread-count?user_id=%20")

        assertEquals(HttpStatusCode.BadRequest, response.status)
    }

    @Test
    fun `get notification by id returns the notification`() = testApplication {
        installService()
        coEvery { notificationService.getNotificationById("notif-1") } returns notification("notif-1")

        val response = client.get("/api/v1/notifications/notif-1")

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("\"id\":\"notif-1\""))
    }

    @Test
    fun `get notification by id returns 404 when it does not exist`() = testApplication {
        installService()
        coEvery { notificationService.getNotificationById("missing") } returns null

        val response = client.get("/api/v1/notifications/missing")

        assertEquals(HttpStatusCode.NotFound, response.status)
        assertTrue(response.bodyAsText().contains("Notification not found"))
    }

    @Test
    fun `mark as read returns 204 on success and 404 when unknown`() = testApplication {
        installService()
        coEvery { notificationService.markAsRead("notif-1") } returns true
        coEvery { notificationService.markAsRead("missing") } returns false

        assertEquals(HttpStatusCode.NoContent, client.put("/api/v1/notifications/notif-1/read").status)
        assertEquals(HttpStatusCode.NotFound, client.put("/api/v1/notifications/missing/read").status)
    }

    @Test
    fun `mark all as read returns the number of updated notifications`() = testApplication {
        installService()
        coEvery { notificationService.markAllAsRead("user-1") } returns 3

        val response = client.put("/api/v1/notifications/read-all") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("""{"markedCount":3}""", response.bodyAsText())
    }

    @Test
    fun `mark all as read rejects a missing user id`() = testApplication {
        installService()

        assertEquals(HttpStatusCode.BadRequest, client.put("/api/v1/notifications/read-all").status)
    }

    @Test
    fun `delete notification returns 204 on success and 404 when unknown`() = testApplication {
        installService()
        coEvery { notificationService.deleteNotification("notif-1") } returns true
        coEvery { notificationService.deleteNotification("missing") } returns false

        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/notif-1").status)
        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/missing").status)
    }

    @Test
    fun `get preferences returns the stored preferences`() = testApplication {
        installService()
        coEvery { notificationService.getPreferences("user-1") } returns NotificationPreference(
            userId = "user-1",
            channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL)),
        )

        val response = client.get("/api/v1/preferences") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals(
            """{"userId":"user-1","channels":{"file_shared":["EMAIL"]}}""",
            response.bodyAsText(),
        )
    }

    @Test
    fun `get preferences rejects a missing user id`() = testApplication {
        installService()

        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/preferences").status)
    }

    @Test
    fun `put preferences forwards the request to the service`() = testApplication {
        installService()

        val response = client.put("/api/v1/preferences") {
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"user-1","eventType":"file_shared","channels":["EMAIL","PUSH"]}""")
        }

        assertEquals(HttpStatusCode.NoContent, response.status)
        coVerify {
            notificationService.updatePreferences(
                "user-1",
                "file_shared",
                listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH),
            )
        }
    }

    @Test
    fun `unhandled failures are mapped to a 500 by StatusPages`() = testApplication {
        installService()
        coEvery { notificationService.getUnreadCount("user-1") } throws IllegalStateException("boom")

        val response = client.get("/api/v1/notifications/unread-count") {
            header("X-User-ID", "user-1")
        }

        assertEquals(HttpStatusCode.InternalServerError, response.status)
        assertTrue(response.bodyAsText().contains("Internal server error"))
    }

    @Test
    fun `websocket registers the connection, answers ping and cleans up on close`() = testApplication {
        installService()
        val wsClient = createClient { install(ClientWebSockets) }

        wsClient.webSocket("/ws/notifications/user-1") {
            send(Frame.Text("ping"))
            assertEquals("pong", (incoming.receive() as Frame.Text).readText())
            send(Frame.Binary(true, ByteArray(1)))
            assertTrue(webSocketManager.isUserConnected("user-1"))
            close()
        }

        assertEquals(0, webSocketManager.getConnectedUserCount())
    }

    @Test
    fun `response payloads are value objects`() {
        assertEquals(HealthResponse("healthy", "notification-service"), HealthResponse("healthy", "notification-service"))
        assertEquals(
            HealthResponse("healthy", "notification-service").hashCode(),
            HealthResponse("healthy", "notification-service").copy().hashCode(),
        )
        assertTrue(HealthResponse("healthy", "notification-service").toString().contains("healthy"))
        assertEquals("notification-service", HealthResponse("healthy", "notification-service").component2())

        assertEquals(ErrorResponse("nope"), ErrorResponse("nope"))
        assertEquals(ErrorResponse("nope").hashCode(), ErrorResponse("nope").hashCode())
        assertTrue(ErrorResponse("nope").toString().contains("nope"))
        assertEquals("other", ErrorResponse("nope").copy(error = "other").component1())

        assertEquals(MarkAllReadResponse(3), MarkAllReadResponse(3))
        assertEquals(MarkAllReadResponse(3).hashCode(), MarkAllReadResponse(3).hashCode())
        assertTrue(MarkAllReadResponse(3).toString().contains("3"))
        assertEquals(4, MarkAllReadResponse(3).copy(markedCount = 4).component1())
    }

    @Test
    fun `websocket rejects a blank user id`() = testApplication {
        installService()
        val wsClient = createClient { install(ClientWebSockets) }

        wsClient.webSocket("/ws/notifications/%20") {
            assertEquals(
                CloseReason.Codes.VIOLATED_POLICY.code,
                closeReason.await()?.code,
            )
        }

        assertEquals(0, webSocketManager.getConnectedUserCount())
    }
}
