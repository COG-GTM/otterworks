package com.otterworks.notification.routes

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
import io.ktor.serialization.kotlinx.json.json
import io.ktor.server.plugins.contentnegotiation.ContentNegotiation
import io.ktor.server.testing.ApplicationTestBuilder
import io.ktor.server.testing.testApplication
import io.ktor.server.application.install
import io.ktor.server.websocket.WebSockets
import io.ktor.websocket.Frame
import io.ktor.websocket.close
import io.ktor.websocket.readText
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.serialization.json.Json
import org.koin.core.context.stopKoin
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class RoutesTest {

    private val notificationService = mockk<NotificationService>()
    private val webSocketManager = WebSocketManager()
    private val prometheusRegistry = PrometheusMeterRegistry(PrometheusConfig.DEFAULT)
    private val json = Json { ignoreUnknownKeys = true }

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    private fun ApplicationTestBuilder.installNotificationApp() {
        application {
            val app = this
            app.install(ContentNegotiation) {
                json(Json { encodeDefaults = true; ignoreUnknownKeys = true })
            }
            app.install(WebSockets)
            app.install(Koin) {
                modules(
                    module {
                        single { notificationService }
                        single { webSocketManager }
                    }
                )
            }
            app.configureRouting(prometheusRegistry)
        }
    }

    private fun notification(id: String, read: Boolean = false) = Notification(
        id = id,
        userId = "user-1",
        type = "file_shared",
        title = "File Shared With You",
        message = "A file has been shared with you.",
        resourceId = "file-1",
        resourceType = "file",
        actorId = "actor-1",
        read = read,
        deliveredVia = listOf("in_app"),
        createdAt = "2024-01-01T00:00:00Z",
    )

    @Test
    fun `health reports the service name`() = testApplication {
        installNotificationApp()

        val response = client.get("/health")

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals(
            HealthResponse(status = "healthy", service = "notification-service"),
            json.decodeFromString(HealthResponse.serializer(), response.bodyAsText()),
        )
    }

    @Test
    fun `metrics exposes the prometheus scrape`() = testApplication {
        installNotificationApp()
        prometheusRegistry.counter("notifications.processed").increment()

        val response = client.get("/metrics")

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("notifications_processed_total"), response.bodyAsText())
    }

    @Test
    fun `listing notifications uses the X-User-ID header and reports more pages`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.getNotifications("user-1", 1, 20) } returns
            Pair(listOf(notification("n-1")), 55)

        val response = client.get("/api/v1/notifications") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        val body = response.bodyAsText()
        assertTrue(body.contains("\"total\":55"), body)
        assertTrue(body.contains("\"page\":1"), body)
        assertTrue(body.contains("\"pageSize\":20"), body)
        assertTrue(body.contains("\"hasMore\":true"), body)
        assertTrue(body.contains("\"id\":\"n-1\""), body)
    }

    @Test
    fun `listing notifications honours page and page_size query parameters`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.getNotifications("user-9", 3, 5) } returns Pair(emptyList(), 12)

        val response = client.get("/api/v1/notifications?user_id=user-9&page=3&page_size=5")

        assertEquals(HttpStatusCode.OK, response.status)
        val body = response.bodyAsText()
        assertTrue(body.contains("\"hasMore\":false"), body)
        assertTrue(body.contains("\"data\":[]"), body)
        coVerify(exactly = 1) { notificationService.getNotifications("user-9", 3, 5) }
    }

    @Test
    fun `listing notifications falls back to defaults for unparseable paging`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.getNotifications("user-1", 1, 20) } returns Pair(emptyList(), 0)

        val response = client.get("/api/v1/notifications?user_id=user-1&page=abc&page_size=xyz")

        assertEquals(HttpStatusCode.OK, response.status)
        coVerify(exactly = 1) { notificationService.getNotifications("user-1", 1, 20) }
    }

    @Test
    fun `listing notifications rejects a missing or blank user id`() = testApplication {
        installNotificationApp()

        val missing = client.get("/api/v1/notifications")
        val blank = client.get("/api/v1/notifications") { header("X-User-ID", "  ") }

        assertEquals(HttpStatusCode.BadRequest, missing.status)
        assertEquals(HttpStatusCode.BadRequest, blank.status)
        assertTrue(missing.bodyAsText().contains("user_id is required"), missing.bodyAsText())
        coVerify(exactly = 0) { notificationService.getNotifications(any(), any(), any()) }
    }

    @Test
    fun `unread count is returned for the requested user`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.getUnreadCount("user-1") } returns 4

        val response = client.get("/api/v1/notifications/unread-count?user_id=user-1")

        assertEquals(HttpStatusCode.OK, response.status)
        val body = response.bodyAsText()
        assertTrue(body.contains("\"unreadCount\":4"), body)
        assertTrue(body.contains("\"userId\":\"user-1\""), body)
    }

    @Test
    fun `unread count prefers the X-User-ID header over the query parameter`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.getUnreadCount("header-user") } returns 1

        val response = client.get("/api/v1/notifications/unread-count?user_id=query-user") {
            header("X-User-ID", "header-user")
        }

        assertEquals(HttpStatusCode.OK, response.status)
        coVerify(exactly = 1) { notificationService.getUnreadCount("header-user") }
        coVerify(exactly = 0) { notificationService.getUnreadCount("query-user") }
    }

    @Test
    fun `unread count rejects a missing user id`() = testApplication {
        installNotificationApp()

        val response = client.get("/api/v1/notifications/unread-count")

        assertEquals(HttpStatusCode.BadRequest, response.status)
        assertEquals(
            ErrorResponse("user_id is required (via X-User-ID header or query parameter)"),
            json.decodeFromString(ErrorResponse.serializer(), response.bodyAsText()),
        )
        coVerify(exactly = 0) { notificationService.getUnreadCount(any()) }
    }

    @Test
    fun `fetching a single notification returns it or 404`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.getNotificationById("n-1") } returns notification("n-1")
        coEvery { notificationService.getNotificationById("missing") } returns null

        val found = client.get("/api/v1/notifications/n-1")
        val notFound = client.get("/api/v1/notifications/missing")

        assertEquals(HttpStatusCode.OK, found.status)
        assertTrue(found.bodyAsText().contains("\"id\":\"n-1\""), found.bodyAsText())
        assertEquals(HttpStatusCode.NotFound, notFound.status)
        assertTrue(notFound.bodyAsText().contains("Notification not found"), notFound.bodyAsText())
    }

    @Test
    fun `marking a notification as read returns 204 or 404`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.markAsRead("n-1") } returns true
        coEvery { notificationService.markAsRead("missing") } returns false

        assertEquals(HttpStatusCode.NoContent, client.put("/api/v1/notifications/n-1/read").status)

        val notFound = client.put("/api/v1/notifications/missing/read")
        assertEquals(HttpStatusCode.NotFound, notFound.status)
        assertTrue(notFound.bodyAsText().contains("Notification not found"), notFound.bodyAsText())
    }

    @Test
    fun `marking everything as read reports how many were updated`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.markAllAsRead("user-1") } returns 7

        val response = client.put("/api/v1/notifications/read-all") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals(
            MarkAllReadResponse(markedCount = 7),
            json.decodeFromString(MarkAllReadResponse.serializer(), response.bodyAsText()),
        )
    }

    @Test
    fun `marking everything as read accepts the user id as a query parameter`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.markAllAsRead("user-2") } returns 0

        val response = client.put("/api/v1/notifications/read-all?user_id=user-2")

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("\"markedCount\":0"), response.bodyAsText())
    }

    @Test
    fun `marking everything as read rejects a missing user id`() = testApplication {
        installNotificationApp()

        val response = client.put("/api/v1/notifications/read-all")

        assertEquals(HttpStatusCode.BadRequest, response.status)
        coVerify(exactly = 0) { notificationService.markAllAsRead(any()) }
    }

    @Test
    fun `deleting a notification returns 204 or 404`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.deleteNotification("n-1") } returns true
        coEvery { notificationService.deleteNotification("missing") } returns false

        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/n-1").status)
        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/missing").status)
    }

    @Test
    fun `preferences are returned for the requested user`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.getPreferences("user-1") } returns NotificationPreference(
            userId = "user-1",
            channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL)),
        )

        val response = client.get("/api/v1/preferences") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        val body = response.bodyAsText()
        assertTrue(body.contains("\"userId\":\"user-1\""), body)
        assertTrue(body.contains("\"file_shared\":[\"EMAIL\"]"), body)
    }

    @Test
    fun `preferences accept the user id as a query parameter`() = testApplication {
        installNotificationApp()
        coEvery { notificationService.getPreferences("user-2") } returns
            NotificationPreference(userId = "user-2", channels = emptyMap())

        val response = client.get("/api/v1/preferences?user_id=user-2")

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("\"userId\":\"user-2\""), response.bodyAsText())
    }

    @Test
    fun `preferences reject a missing user id`() = testApplication {
        installNotificationApp()

        val response = client.get("/api/v1/preferences")

        assertEquals(HttpStatusCode.BadRequest, response.status)
        coVerify(exactly = 0) { notificationService.getPreferences(any()) }
    }

    @Test
    fun `updating preferences forwards the requested channels`() = testApplication {
        installNotificationApp()
        val channels = slot<List<DeliveryChannel>>()
        coEvery {
            notificationService.updatePreferences("user-1", "file_shared", capture(channels))
        } returns Unit

        val response = client.put("/api/v1/preferences") {
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"user-1","eventType":"file_shared","channels":["EMAIL","PUSH"]}""")
        }

        assertEquals(HttpStatusCode.NoContent, response.status)
        assertEquals(listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH), channels.captured)
    }

    @Test
    fun `the websocket registers the connection and answers ping with pong`() = testApplication {
        installNotificationApp()
        val wsClient = createClient { install(ClientWebSockets) }

        wsClient.webSocket("/ws/notifications/user-1") {
            send(Frame.Text("ping"))
            assertEquals("pong", (incoming.receive() as Frame.Text).readText())
            assertTrue(webSocketManager.isUserConnected("user-1"))
            send(Frame.Text("hello"))
            send(Frame.Binary(true, ByteArray(2)))
            close()
        }

        assertFalse(webSocketManager.isUserConnected("user-1"))
    }

    @Test
    fun `the websocket rejects a blank user id`() = testApplication {
        installNotificationApp()
        val wsClient = createClient { install(ClientWebSockets) }

        wsClient.webSocket("/ws/notifications/%20") {
            assertEquals(0, webSocketManager.getConnectedUserCount())
        }

        assertEquals(0, webSocketManager.getConnectedUserCount())
    }
}
