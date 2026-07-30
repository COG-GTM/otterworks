package com.otterworks.notification.routes

import com.otterworks.notification.configurePlugins
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.notification
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.testConfig
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
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.server.application.install
import io.ktor.server.testing.ApplicationTestBuilder
import io.ktor.server.testing.testApplication
import io.ktor.websocket.Frame
import io.ktor.websocket.close
import io.ktor.websocket.readText
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.delay
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.koin.core.context.GlobalContext
import org.koin.core.context.stopKoin
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class RoutesTest {

    private val service = mockk<NotificationService>(relaxed = true)
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)
    private val registry = PrometheusMeterRegistry(PrometheusConfig.DEFAULT)

    @AfterTest
    fun tearDown() {
        if (GlobalContext.getOrNull() != null) stopKoin()
    }

    private fun ApplicationTestBuilder.notificationApp() {
        application {
            configurePlugins(testConfig())
            install(Koin) {
                modules(
                    module {
                        single { service }
                        single { webSocketManager }
                    },
                )
            }
            configureRouting(registry)
        }
    }

    private fun String.field(name: String): String =
        (Json.parseToJsonElement(this) as JsonObject).getValue(name).jsonPrimitive.content

    /** Retries an assertion briefly, for state a server-side coroutine updates after the client returns. */
    private suspend fun eventually(assertion: () -> Unit) {
        var failure: Throwable? = null
        repeat(100) {
            try {
                assertion()
                return
            } catch (t: Throwable) {
                failure = t
                delay(20)
            }
        }
        throw failure ?: AssertionError("assertion never ran")
    }

    // ---------- infrastructure endpoints ----------

    @Test
    fun `health reports the service name`() = testApplication {
        notificationApp()

        val response = client.get("/health")

        assertEquals(HttpStatusCode.OK, response.status)
        val body = response.bodyAsText()
        assertEquals("healthy", body.field("status"))
        assertEquals("notification-service", body.field("service"))
    }

    @Test
    fun `metrics exposes the prometheus scrape in plain text`() = testApplication {
        notificationApp()
        registry.counter("notifications.processed").increment()

        val response = client.get("/metrics")

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals(
            ContentType.Text.Plain,
            ContentType.parse(response.headers[HttpHeaders.ContentType]!!).withoutParameters(),
        )
        assertTrue(response.bodyAsText().contains("notifications_processed_total"))
    }

    // ---------- GET /api/v1/notifications ----------

    @Test
    fun `listing notifications resolves the user from the X-User-ID header`() = testApplication {
        notificationApp()
        coEvery { service.getNotifications("user-1", 1, 20) } returns Pair(listOf(notification()), 1)

        val response = client.get("/api/v1/notifications") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        val body = response.bodyAsText()
        assertEquals("1", body.field("total"))
        assertEquals("1", body.field("page"))
        assertEquals("20", body.field("pageSize"))
        assertEquals("false", body.field("hasMore"))
        assertTrue(body.contains("\"id\":\"n-1\""))
    }

    @Test
    fun `listing notifications honours user_id page and page_size query parameters`() = testApplication {
        notificationApp()
        coEvery { service.getNotifications("user-2", 2, 5) } returns Pair(listOf(notification(id = "n-6")), 42)

        val body = client.get("/api/v1/notifications?user_id=user-2&page=2&page_size=5").bodyAsText()

        assertEquals("42", body.field("total"))
        assertEquals("2", body.field("page"))
        assertEquals("5", body.field("pageSize"))
        assertEquals("true", body.field("hasMore"))
    }

    @Test
    fun `listing notifications falls back to page 1 size 20 for unparseable paging`() = testApplication {
        notificationApp()
        coEvery { service.getNotifications("user-1", 1, 20) } returns Pair(emptyList(), 0)

        val response = client.get("/api/v1/notifications?user_id=user-1&page=abc&page_size=xyz")

        assertEquals(HttpStatusCode.OK, response.status)
        coVerify { service.getNotifications("user-1", 1, 20) }
    }

    @Test
    fun `listing notifications requires a user id`() = testApplication {
        notificationApp()

        val blank = client.get("/api/v1/notifications?user_id=%20")
        val missing = client.get("/api/v1/notifications")

        assertEquals(HttpStatusCode.BadRequest, blank.status)
        assertEquals(HttpStatusCode.BadRequest, missing.status)
        assertTrue(missing.bodyAsText().field("error").contains("user_id is required"))
        coVerify(exactly = 0) { service.getNotifications(any(), any(), any()) }
    }

    // ---------- unread count ----------

    @Test
    fun `unread-count returns the count for the requested user`() = testApplication {
        notificationApp()
        coEvery { service.getUnreadCount("user-1") } returns 7

        val body = client.get("/api/v1/notifications/unread-count") { header("X-User-ID", "user-1") }.bodyAsText()

        assertEquals("user-1", body.field("userId"))
        assertEquals("7", body.field("unreadCount"))
    }

    @Test
    fun `unread-count requires a user id`() = testApplication {
        notificationApp()

        val response = client.get("/api/v1/notifications/unread-count")

        assertEquals(HttpStatusCode.BadRequest, response.status)
        coVerify(exactly = 0) { service.getUnreadCount(any()) }
    }

    // ---------- single notification ----------

    @Test
    fun `fetching a notification by id returns it when it exists`() = testApplication {
        notificationApp()
        coEvery { service.getNotificationById("n-1") } returns notification(id = "n-1")

        val response = client.get("/api/v1/notifications/n-1")

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("n-1", response.bodyAsText().field("id"))
    }

    @Test
    fun `fetching an unknown notification returns 404`() = testApplication {
        notificationApp()
        coEvery { service.getNotificationById("nope") } returns null

        val response = client.get("/api/v1/notifications/nope")

        assertEquals(HttpStatusCode.NotFound, response.status)
        assertEquals("Notification not found", response.bodyAsText().field("error"))
    }

    // ---------- mark as read ----------

    @Test
    fun `marking a notification read returns 204`() = testApplication {
        notificationApp()
        coEvery { service.markAsRead("n-1") } returns true

        assertEquals(HttpStatusCode.NoContent, client.put("/api/v1/notifications/n-1/read").status)
    }

    @Test
    fun `marking an unknown notification read returns 404`() = testApplication {
        notificationApp()
        coEvery { service.markAsRead("nope") } returns false

        val response = client.put("/api/v1/notifications/nope/read")

        assertEquals(HttpStatusCode.NotFound, response.status)
        assertEquals("Notification not found", response.bodyAsText().field("error"))
    }

    @Test
    fun `read-all reports how many notifications were marked`() = testApplication {
        notificationApp()
        coEvery { service.markAllAsRead("user-1") } returns 3

        val response = client.put("/api/v1/notifications/read-all") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("3", response.bodyAsText().field("markedCount"))
    }

    @Test
    fun `read-all requires a user id`() = testApplication {
        notificationApp()

        assertEquals(HttpStatusCode.BadRequest, client.put("/api/v1/notifications/read-all").status)
        coVerify(exactly = 0) { service.markAllAsRead(any()) }
    }

    // ---------- delete ----------

    @Test
    fun `deleting a notification returns 204`() = testApplication {
        notificationApp()
        coEvery { service.deleteNotification("n-1") } returns true

        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/n-1").status)
    }

    @Test
    fun `deleting an unknown notification returns 404`() = testApplication {
        notificationApp()
        coEvery { service.deleteNotification("nope") } returns false

        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/nope").status)
    }

    // ---------- preferences ----------

    @Test
    fun `preferences are returned for the requested user`() = testApplication {
        notificationApp()
        coEvery { service.getPreferences("user-1") } returns NotificationPreference(
            userId = "user-1",
            channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL)),
        )

        val body = client.get("/api/v1/preferences?user_id=user-1").bodyAsText()

        assertEquals("user-1", body.field("userId"))
        assertTrue(body.contains("\"file_shared\":[\"EMAIL\"]"))
    }

    @Test
    fun `preferences require a user id`() = testApplication {
        notificationApp()

        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/preferences").status)
        coVerify(exactly = 0) { service.getPreferences(any()) }
    }

    @Test
    fun `updating preferences delegates to the service and returns 204`() = testApplication {
        notificationApp()

        val response = client.put("/api/v1/preferences") {
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"user-1","eventType":"comment_added","channels":["EMAIL","IN_APP"]}""")
        }

        assertEquals(HttpStatusCode.NoContent, response.status)
        coVerify {
            service.updatePreferences(
                "user-1",
                "comment_added",
                listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP),
            )
        }
    }

    // ---------- error handling (StatusPages, installed by configurePlugins) ----------

    @Test
    fun `an unexpected service failure is turned into a 500 json error`() = testApplication {
        notificationApp()
        coEvery { service.getUnreadCount("user-1") } throws IllegalStateException("DynamoDB down")

        val response = client.get("/api/v1/notifications/unread-count?user_id=user-1")

        assertEquals(HttpStatusCode.InternalServerError, response.status)
        assertEquals("Internal server error", response.bodyAsText().field("error"))
    }

    // ---------- websocket ----------

    @Test
    fun `websocket clients are registered, answer ping with pong and are deregistered on close`() =
        testApplication {
            notificationApp()
            val wsClient = createClient { install(ClientWebSockets) }

            wsClient.webSocket("/ws/notifications/user-1") {
                send(Frame.Text("ping"))
                val reply = incoming.receive() as Frame.Text
                assertEquals("pong", reply.readText())

                send(Frame.Text("hello"))
                send(Frame.Binary(true, ByteArray(2)))
                close()
            }

            verify { webSocketManager.addConnection("user-1", any()) }
            eventually { verify { webSocketManager.removeConnection("user-1", any()) } }
        }

    @Test
    fun `websocket connections without a user id are rejected`() = testApplication {
        notificationApp()
        val wsClient = createClient { install(ClientWebSockets) }

        wsClient.webSocket("/ws/notifications/%20") {
            val reason = closeReason.await()
            assertEquals(io.ktor.websocket.CloseReason.Codes.VIOLATED_POLICY.code, reason?.code)
            assertEquals("userId is required", reason?.message)
        }

        verify(exactly = 0) { webSocketManager.addConnection(any(), any()) }
    }
}
