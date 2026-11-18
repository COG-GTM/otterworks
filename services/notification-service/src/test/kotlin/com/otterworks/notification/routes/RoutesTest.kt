package com.otterworks.notification.routes

import com.otterworks.notification.configurePlugins
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.model.PaginatedResponse
import com.otterworks.notification.model.UnreadCountResponse
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.testConfig
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.HttpClient
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
import io.ktor.server.application.install
import io.ktor.server.testing.ApplicationTestBuilder
import io.ktor.server.testing.testApplication
import io.ktor.websocket.CloseReason
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.Json
import org.koin.core.context.stopKoin
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import io.ktor.client.plugins.websocket.WebSockets as ClientWebSockets

class RoutesTest {

    private val service = mockk<NotificationService>(relaxed = true)
    private val wsManager = WebSocketManager()
    private val json = Json { ignoreUnknownKeys = true }
    private val notification = Notification(id = "n1", userId = "u1", type = "file_shared", title = "t", message = "m", createdAt = "now")

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    private fun routesTest(block: suspend ApplicationTestBuilder.() -> Unit) = testApplication {
        application {
            configurePlugins(testConfig())
            install(Koin) {
                modules(module {
                    single { service }
                    single { wsManager }
                })
            }
            configureRouting(PrometheusMeterRegistry(PrometheusConfig.DEFAULT))
        }
        block()
    }

    @Test
    fun `health and metrics`() = routesTest {
        val health = client.get("/health")
        assertEquals(HttpStatusCode.OK, health.status)
        assertEquals(HealthResponse("healthy", "notification-service"), json.decodeFromString(health.bodyAsText()))

        val metrics = client.get("/metrics")
        assertEquals(HttpStatusCode.OK, metrics.status)
        assertTrue(metrics.headers["Content-Type"]!!.startsWith("text/plain"))
    }

    @Test
    fun `user-scoped endpoints require a user id`() = routesTest {
        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/notifications").status)
        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/notifications/unread-count").status)
        assertEquals(HttpStatusCode.BadRequest, client.put("/api/v1/notifications/read-all").status)
        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/preferences").status)
        val blank = client.get("/api/v1/notifications") { header("X-User-ID", " ") }
        assertEquals(HttpStatusCode.BadRequest, blank.status)
        assertTrue(blank.bodyAsText().contains("user_id is required"))
    }

    @Test
    fun `list notifications uses header and pagination defaults`() = routesTest {
        coEvery { service.getNotifications("u1", 1, 20) } returns Pair(listOf(notification), 1)

        val res = client.get("/api/v1/notifications") { header("X-User-ID", "u1") }

        assertEquals(HttpStatusCode.OK, res.status)
        val body = json.decodeFromString<PaginatedResponse<Notification>>(res.bodyAsText())
        assertEquals(PaginatedResponse(listOf(notification), 1, 1, 20, false), body)
    }

    @Test
    fun `list notifications uses query params and computes hasMore`() = routesTest {
        coEvery { service.getNotifications("u2", 2, 5) } returns Pair(listOf(notification), 11)

        val res = client.get("/api/v1/notifications?user_id=u2&page=2&page_size=5")

        val body = json.decodeFromString<PaginatedResponse<Notification>>(res.bodyAsText())
        assertEquals(2, body.page)
        assertEquals(5, body.pageSize)
        assertEquals(11, body.total)
        assertTrue(body.hasMore)
    }

    @Test
    fun `list notifications ignores non-numeric paging`() = routesTest {
        coEvery { service.getNotifications("u1", 1, 20) } returns Pair(emptyList(), 0)
        val res = client.get("/api/v1/notifications?user_id=u1&page=x&page_size=y")
        assertEquals(HttpStatusCode.OK, res.status)
        coVerify { service.getNotifications("u1", 1, 20) }
    }

    @Test
    fun `unread count`() = routesTest {
        coEvery { service.getUnreadCount("u1") } returns 4
        val res = client.get("/api/v1/notifications/unread-count") { header("X-User-ID", "u1") }
        assertEquals(UnreadCountResponse("u1", 4), json.decodeFromString(res.bodyAsText()))
    }

    @Test
    fun `get notification by id found and not found`() = routesTest {
        coEvery { service.getNotificationById("n1") } returns notification
        coEvery { service.getNotificationById("nope") } returns null

        val found = client.get("/api/v1/notifications/n1")
        assertEquals(HttpStatusCode.OK, found.status)
        assertEquals(notification, json.decodeFromString(found.bodyAsText()))

        val missing = client.get("/api/v1/notifications/nope")
        assertEquals(HttpStatusCode.NotFound, missing.status)
        assertEquals(ErrorResponse("Notification not found"), json.decodeFromString(missing.bodyAsText()))
    }

    @Test
    fun `mark as read`() = routesTest {
        coEvery { service.markAsRead("n1") } returns true
        coEvery { service.markAsRead("nope") } returns false
        assertEquals(HttpStatusCode.NoContent, client.put("/api/v1/notifications/n1/read").status)
        assertEquals(HttpStatusCode.NotFound, client.put("/api/v1/notifications/nope/read").status)
    }

    @Test
    fun `mark all as read`() = routesTest {
        coEvery { service.markAllAsRead("u1") } returns 3
        val res = client.put("/api/v1/notifications/read-all?user_id=u1")
        assertEquals(HttpStatusCode.OK, res.status)
        assertEquals(MarkAllReadResponse(3), json.decodeFromString(res.bodyAsText()))
    }

    @Test
    fun `delete notification`() = routesTest {
        coEvery { service.deleteNotification("n1") } returns true
        coEvery { service.deleteNotification("nope") } returns false
        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/n1").status)
        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/nope").status)
    }

    @Test
    fun `get and update preferences`() = routesTest {
        coEvery { service.getPreferences("u1") } returns NotificationPreference("u1")
        val got = client.get("/api/v1/preferences") { header("X-User-ID", "u1") }
        assertEquals(NotificationPreference("u1"), json.decodeFromString(got.bodyAsText()))

        val put = client.put("/api/v1/preferences") {
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"u1","eventType":"file_shared","channels":["EMAIL","PUSH"]}""")
        }
        assertEquals(HttpStatusCode.NoContent, put.status)
        coVerify { service.updatePreferences("u1", "file_shared", listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH)) }
    }

    @Test
    fun `unhandled exceptions map to 500`() = routesTest {
        coEvery { service.getUnreadCount("u1") } throws IllegalStateException("dynamo down")
        val res = client.get("/api/v1/notifications/unread-count?user_id=u1")
        assertEquals(HttpStatusCode.InternalServerError, res.status)
        assertEquals("""{"error":"Internal server error"}""", res.bodyAsText())
    }

    private fun ApplicationTestBuilder.wsClient(): HttpClient = createClient { install(ClientWebSockets) }

    @Test
    fun `websocket registers user, answers ping and receives pushes`() = routesTest {
        wsClient().webSocket("/ws/notifications/u1") {
            send(Frame.Text("ping"))
            assertEquals("pong", (incoming.receive() as Frame.Text).readText())
            assertTrue(wsManager.isUserConnected("u1"))

            send(Frame.Text("hello"))
            send(Frame.Binary(true, byteArrayOf(1, 2)))
            assertEquals(1, wsManager.pushNotification("u1", notification))
            val pushed = (incoming.receive() as Frame.Text).readText()
            assertEquals(notification, json.decodeFromString(pushed))
        }
        withTimeout(5000) {
            while (wsManager.isUserConnected("u1")) delay(10)
        }
        assertFalse(wsManager.isUserConnected("u1"))
    }

    @Test
    fun `websocket rejects blank user id`() = routesTest {
        wsClient().webSocket("/ws/notifications/%20") {
            val reason = closeReason.await()
            assertEquals(CloseReason.Codes.VIOLATED_POLICY.code, reason?.code)
        }
        assertEquals(0, wsManager.getConnectedUserCount())
    }
}
