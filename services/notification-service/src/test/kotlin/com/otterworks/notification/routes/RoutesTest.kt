package com.otterworks.notification.routes

import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.configurePlugins
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.plugins.websocket.WebSockets
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
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.verify
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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

    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "q",
        snsTopicArn = "t",
        dynamoDbTableNotifications = "n",
        dynamoDbTablePreferences = "p",
        sesFromEmail = "e",
        sqsPollIntervalMs = 1000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )

    private val notification = Notification(
        id = "n-1",
        userId = "user-1",
        type = "file_shared",
        title = "File Shared With You",
        message = "msg",
        createdAt = "2024-01-01T00:00:00Z",
    )

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    private fun routesTest(block: suspend ApplicationTestBuilder.() -> Unit) = testApplication {
        application {
            configurePlugins(config)
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

    private fun json(text: String) = Json.parseToJsonElement(text).jsonObject

    @Test
    fun `health reports the service as healthy`() = routesTest {
        val response = client.get("/health")
        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("healthy", json(response.bodyAsText())["status"]!!.jsonPrimitive.content)
    }

    @Test
    fun `metrics exposes prometheus text`() = routesTest {
        val response = client.get("/metrics")
        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.headers["Content-Type"]!!.startsWith("text/plain"))
    }

    @Test
    fun `listing notifications requires a user id`() = routesTest {
        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/notifications").status)
        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/notifications/unread-count").status)
        assertEquals(HttpStatusCode.BadRequest, client.put("/api/v1/notifications/read-all").status)
        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/preferences").status)
    }

    @Test
    fun `listing notifications paginates using the header user id`() = routesTest {
        coEvery { service.getNotifications("user-1", 2, 1) } returns Pair(listOf(notification), 3)

        val response = client.get("/api/v1/notifications?page=2&page_size=1") {
            header("X-User-ID", "user-1")
        }

        assertEquals(HttpStatusCode.OK, response.status)
        val body = json(response.bodyAsText())
        assertEquals(3, body["total"]!!.jsonPrimitive.int)
        assertEquals(2, body["page"]!!.jsonPrimitive.int)
        assertEquals(1, body["pageSize"]!!.jsonPrimitive.int)
        assertEquals(true, body["hasMore"]!!.jsonPrimitive.boolean)
        assertEquals("n-1", body["data"]!!.jsonArray.single().jsonObject["id"]!!.jsonPrimitive.content)
    }

    @Test
    fun `listing notifications defaults paging and accepts the user_id query parameter`() = routesTest {
        coEvery { service.getNotifications("user-2", 1, 20) } returns Pair(emptyList(), 0)

        val response = client.get("/api/v1/notifications?user_id=user-2&page=abc")

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals(false, json(response.bodyAsText())["hasMore"]!!.jsonPrimitive.boolean)
        coVerify { service.getNotifications("user-2", 1, 20) }
    }

    @Test
    fun `unread count is returned for the user`() = routesTest {
        coEvery { service.getUnreadCount("user-1") } returns 4

        val response = client.get("/api/v1/notifications/unread-count") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals(4, json(response.bodyAsText())["unreadCount"]!!.jsonPrimitive.int)
    }

    @Test
    fun `get by id returns the notification or 404`() = routesTest {
        coEvery { service.getNotificationById("n-1") } returns notification
        coEvery { service.getNotificationById("missing") } returns null

        val found = client.get("/api/v1/notifications/n-1")
        assertEquals(HttpStatusCode.OK, found.status)
        assertEquals("user-1", json(found.bodyAsText())["userId"]!!.jsonPrimitive.content)

        assertEquals(HttpStatusCode.NotFound, client.get("/api/v1/notifications/missing").status)
    }

    @Test
    fun `mark as read returns 204 or 404`() = routesTest {
        coEvery { service.markAsRead("n-1") } returns true
        coEvery { service.markAsRead("missing") } returns false

        assertEquals(HttpStatusCode.NoContent, client.put("/api/v1/notifications/n-1/read").status)
        assertEquals(HttpStatusCode.NotFound, client.put("/api/v1/notifications/missing/read").status)
    }

    @Test
    fun `mark all as read returns the marked count`() = routesTest {
        coEvery { service.markAllAsRead("user-1") } returns 7

        val response = client.put("/api/v1/notifications/read-all") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals(7, json(response.bodyAsText())["markedCount"]!!.jsonPrimitive.int)
        coVerify(exactly = 0) { service.markAsRead(any()) }
    }

    @Test
    fun `delete returns 204 or 404`() = routesTest {
        coEvery { service.deleteNotification("n-1") } returns true
        coEvery { service.deleteNotification("missing") } returns false

        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/n-1").status)
        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/missing").status)
    }

    @Test
    fun `preferences are returned for the user`() = routesTest {
        coEvery { service.getPreferences("user-1") } returns NotificationPreference(userId = "user-1")

        val response = client.get("/api/v1/preferences?user_id=user-1")

        assertEquals(HttpStatusCode.OK, response.status)
        val channels = json(response.bodyAsText())["channels"]!!.jsonObject
        assertEquals(
            listOf("EMAIL", "IN_APP", "PUSH"),
            channels["file_shared"]!!.jsonArray.map { it.jsonPrimitive.content },
        )
    }

    @Test
    fun `updating preferences forwards the request to the service`() = routesTest {
        val response = client.put("/api/v1/preferences") {
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"user-1","eventType":"comment_added","channels":["EMAIL"]}""")
        }

        assertEquals(HttpStatusCode.NoContent, response.status)
        coVerify { service.updatePreferences("user-1", "comment_added", listOf(DeliveryChannel.EMAIL)) }
    }

    @Test
    fun `service failures surface as 500`() = routesTest {
        coEvery { service.getUnreadCount("user-1") } throws RuntimeException("dynamo down")

        val response = client.get("/api/v1/notifications/unread-count") { header("X-User-ID", "user-1") }

        assertEquals(HttpStatusCode.InternalServerError, response.status)
    }

    @Test
    fun `websocket registers the session and answers ping`() = routesTest {
        val wsClient = createClient { install(WebSockets) }

        wsClient.webSocket("/ws/notifications/user-1") {
            send(Frame.Text("ping"))
            val reply = incoming.receive() as Frame.Text
            assertEquals("pong", reply.readText())
        }

        verify { webSocketManager.addConnection("user-1", any()) }
        verify(timeout = 5000) { webSocketManager.removeConnection("user-1", any()) }
    }
}
