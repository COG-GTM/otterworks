package com.otterworks.notification.routes

import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.HttpClient
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import io.ktor.server.application.install
import io.ktor.server.plugins.contentnegotiation.ContentNegotiation
import io.ktor.server.testing.ApplicationTestBuilder
import io.ktor.server.testing.testApplication
import io.ktor.server.websocket.WebSockets
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.verify
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class RoutesTest {

    private val service = mockk<NotificationService>()
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)

    private val userIdRequired = "user_id is required (via X-User-ID header or query parameter)"

    private fun notification(id: String) = Notification(
        id = id,
        userId = "user-1",
        type = "file_shared",
        title = "Shared",
        message = "A file was shared",
        createdAt = "2024-01-01T00:00:00Z",
    )

    private fun routesTest(block: suspend ApplicationTestBuilder.() -> Unit) = testApplication {
        application {
            install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true; encodeDefaults = true }) }
            install(WebSockets)
            install(Koin) {
                modules(module {
                    single { service }
                    single { webSocketManager }
                })
            }
            configureRouting(PrometheusMeterRegistry(PrometheusConfig.DEFAULT))
        }
        block()
    }

    private suspend fun HttpResponse.json(): JsonObject = Json.parseToJsonElement(bodyAsText()).jsonObject

    private fun JsonObject.str(key: String) = getValue(key).jsonPrimitive.content

    @Test
    fun `health reports service status`() = routesTest {
        val response = client.get("/health")
        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("healthy", response.json().str("status"))
        assertEquals("notification-service", response.json().str("service"))
    }

    @Test
    fun `metrics returns plain text scrape`() = routesTest {
        val response = client.get("/metrics")
        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.contentType()?.match(ContentType.Text.Plain) == true)
    }

    @Test
    fun `user scoped routes reject missing user id`() = routesTest {
        val responses = listOf(
            client.get("/api/v1/notifications"),
            client.get("/api/v1/notifications/unread-count"),
            client.put("/api/v1/notifications/read-all"),
            client.get("/api/v1/preferences"),
        )
        responses.forEach {
            assertEquals(HttpStatusCode.BadRequest, it.status)
            assertEquals(userIdRequired, it.json().str("error"))
        }
    }

    @Test
    fun `list notifications paginates for header user`() = routesTest {
        coEvery { service.getNotifications("user-1", 2, 5) } returns (listOf(notification("n-1")) to 11)

        val response = client.get("/api/v1/notifications?page=2&page_size=5") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        val body = response.json()
        assertEquals("11", body.str("total"))
        assertEquals("2", body.str("page"))
        assertEquals("5", body.str("pageSize"))
        assertEquals("true", body.str("hasMore"))
    }

    @Test
    fun `list notifications defaults paging and falls back to query user id`() = routesTest {
        coEvery { service.getNotifications("user-q", 1, 20) } returns (emptyList<Notification>() to 20)

        val response = client.get("/api/v1/notifications?user_id=user-q&page=x")

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("false", response.json().str("hasMore"))
        coVerify { service.getNotifications("user-q", 1, 20) }
    }

    @Test
    fun `unread count and read all use resolved user id`() = routesTest {
        coEvery { service.getUnreadCount("user-1") } returns 3
        coEvery { service.markAllAsRead("user-1") } returns 4

        val unread = client.get("/api/v1/notifications/unread-count") { header("X-User-ID", "user-1") }
        assertEquals("user-1", unread.json().str("userId"))
        assertEquals("3", unread.json().str("unreadCount"))

        val readAll = client.put("/api/v1/notifications/read-all?user_id=user-1")
        assertEquals("4", readAll.json().str("markedCount"))
    }

    @Test
    fun `get notification by id returns 200 or 404`() = routesTest {
        coEvery { service.getNotificationById("n-1") } returns notification("n-1")
        coEvery { service.getNotificationById("missing") } returns null

        val found = client.get("/api/v1/notifications/n-1")
        assertEquals(HttpStatusCode.OK, found.status)
        assertEquals("n-1", found.json().str("id"))

        val missing = client.get("/api/v1/notifications/missing")
        assertEquals(HttpStatusCode.NotFound, missing.status)
        assertEquals("Notification not found", missing.json().str("error"))
    }

    @Test
    fun `mark as read and delete return 204 or 404`() = routesTest {
        coEvery { service.markAsRead("n-1") } returns true
        coEvery { service.markAsRead("missing") } returns false
        coEvery { service.deleteNotification("n-1") } returns true
        coEvery { service.deleteNotification("missing") } returns false

        assertEquals(HttpStatusCode.NoContent, client.put("/api/v1/notifications/n-1/read").status)
        assertEquals(HttpStatusCode.NotFound, client.put("/api/v1/notifications/missing/read").status)
        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/n-1").status)
        val missing = client.delete("/api/v1/notifications/missing")
        assertEquals(HttpStatusCode.NotFound, missing.status)
        assertEquals("Notification not found", missing.json().str("error"))
    }

    @Test
    fun `preferences get and update`() = routesTest {
        coEvery { service.getPreferences("user-1") } returns NotificationPreference(userId = "user-1")
        coEvery { service.updatePreferences(any(), any(), any()) } returns Unit

        val prefs = client.get("/api/v1/preferences") { header("X-User-ID", "user-1") }
        assertEquals(HttpStatusCode.OK, prefs.status)
        assertEquals("user-1", prefs.json().str("userId"))

        val update = client.put("/api/v1/preferences") {
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"user-1","eventType":"file_shared","channels":["EMAIL"]}""")
        }
        assertEquals(HttpStatusCode.NoContent, update.status)
        coVerify { service.updatePreferences("user-1", "file_shared", listOf(DeliveryChannel.EMAIL)) }
    }

    @Test
    fun `websocket answers ping and unregisters on close`() = routesTest {
        val wsClient: HttpClient = createClient { install(io.ktor.client.plugins.websocket.WebSockets) }

        wsClient.webSocket("/ws/notifications/user-1") {
            send(Frame.Text("hello"))
            send(Frame.Text("ping"))
            val reply = incoming.receive() as Frame.Text
            assertEquals("pong", reply.readText())
        }

        verify { webSocketManager.addConnection("user-1", any()) }
        verify(timeout = 5_000) { webSocketManager.removeConnection("user-1", any()) }
    }
}
