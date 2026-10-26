package com.otterworks.notification.routes

import com.auth0.jwt.JWT
import com.auth0.jwt.algorithms.Algorithm
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.configurePlugins
import com.otterworks.notification.model.Notification
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.plugins.websocket.WebSockets
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.client.request.bearerAuth
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.server.routing.routing
import io.ktor.server.testing.ApplicationTestBuilder
import io.ktor.server.testing.testApplication
import io.ktor.websocket.CloseReason
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import java.util.Date
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFails
import kotlin.test.assertTrue

class NotificationRoutesAuthTest {

    private val secret = "notification-test-jwt-secret-0123456789abcdef"
    private val notificationService = mockk<NotificationService>(relaxed = true)
    private val webSocketManager = WebSocketManager()

    private fun config(jwtSecret: String? = secret) = AppConfig(
        port = 0,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "",
        snsTopicArn = "",
        dynamoDbTableNotifications = "notifications",
        dynamoDbTablePreferences = "preferences",
        sesFromEmail = "test@example.com",
        sqsPollIntervalMs = 1,
        sqsMaxMessages = 1,
        sqsWaitTimeSeconds = 1,
        jwtSecret = jwtSecret,
    )

    private fun token(subject: String, signingSecret: String = secret) = JWT.create()
        .withSubject(subject)
        .withClaim("type", "access")
        .withExpiresAt(Date(System.currentTimeMillis() + 60_000))
        .sign(Algorithm.HMAC384(signingSecret))

    private fun notification(id: String, owner: String) =
        Notification(id = id, userId = owner, type = "file_shared", title = "t", message = "m", createdAt = "2024-01-01T00:00:00Z")

    private fun ApplicationTestBuilder.service(jwtSecret: String? = secret) {
        application {
            configurePlugins(config(jwtSecret))
            routing { notificationApiRoutes(notificationService, webSocketManager) }
        }
    }

    @Test
    fun `caller-chosen identity without a token is rejected`() = testApplication {
        service()
        assertEquals(HttpStatusCode.Unauthorized, client.get("/api/v1/notifications?user_id=bob").status)
        assertEquals(
            HttpStatusCode.Unauthorized,
            client.get("/api/v1/notifications") { header("X-User-ID", "bob") }.status,
        )
        assertEquals(HttpStatusCode.Unauthorized, client.get("/api/v1/notifications/unread-count?user_id=bob").status)
        assertEquals(HttpStatusCode.Unauthorized, client.put("/api/v1/notifications/read-all?user_id=bob").status)
        assertEquals(HttpStatusCode.Unauthorized, client.get("/api/v1/preferences?user_id=bob").status)
        assertEquals(HttpStatusCode.Unauthorized, client.delete("/api/v1/notifications/n-1").status)
        coVerify(exactly = 0) { notificationService.getNotifications(any(), any(), any()) }
        coVerify(exactly = 0) { notificationService.markAllAsRead(any()) }
        coVerify(exactly = 0) { notificationService.getPreferences(any()) }
    }

    @Test
    fun `a token signed with another secret is rejected`() = testApplication {
        service()
        val response = client.get("/api/v1/notifications") { bearerAuth(token("bob", "forged-secret-0123456789abcdef0123")) }
        assertEquals(HttpStatusCode.Unauthorized, response.status)
    }

    @Test
    fun `every request is rejected when JWT_SECRET is unset`() = testApplication {
        service(jwtSecret = null)
        assertEquals(
            HttpStatusCode.Unauthorized,
            client.get("/api/v1/notifications") { bearerAuth(token("alice")) }.status,
        )
    }

    @Test
    fun `identity comes from the token, not the header or query`() = testApplication {
        coEvery { notificationService.getNotifications(any(), any(), any()) } returns (emptyList<Notification>() to 0)
        service()
        val response = client.get("/api/v1/notifications?user_id=bob") {
            bearerAuth(token("alice"))
            header("X-User-ID", "bob")
        }
        assertEquals(HttpStatusCode.OK, response.status)
        coVerify(exactly = 1) { notificationService.getNotifications("alice", 1, 20) }
        coVerify(exactly = 0) { notificationService.getNotifications("bob", any(), any()) }
    }

    @Test
    fun `another user's notification is not found and cannot be changed`() = testApplication {
        coEvery { notificationService.getNotificationById("n-bob") } returns notification("n-bob", "bob")
        service()
        val alice = token("alice")
        assertEquals(HttpStatusCode.NotFound, client.get("/api/v1/notifications/n-bob") { bearerAuth(alice) }.status)
        assertEquals(HttpStatusCode.NotFound, client.put("/api/v1/notifications/n-bob/read") { bearerAuth(alice) }.status)
        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/n-bob") { bearerAuth(alice) }.status)
        coVerify(exactly = 0) { notificationService.markAsRead(any()) }
        coVerify(exactly = 0) { notificationService.deleteNotification(any()) }

        coEvery { notificationService.markAsRead("n-bob") } returns true
        assertEquals(
            HttpStatusCode.NoContent,
            client.put("/api/v1/notifications/n-bob/read") { bearerAuth(token("bob")) }.status,
        )
    }

    @Test
    fun `preferences are written for the caller only`() = testApplication {
        service()
        val forOther = client.put("/api/v1/preferences") {
            bearerAuth(token("alice"))
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"bob","eventType":"comment_added","channels":["IN_APP"]}""")
        }
        assertEquals(HttpStatusCode.Forbidden, forOther.status)
        coVerify(exactly = 0) { notificationService.updatePreferences(any(), any(), any()) }

        val forSelf = client.put("/api/v1/preferences") {
            bearerAuth(token("alice"))
            contentType(ContentType.Application.Json)
            setBody("""{"eventType":"comment_added","channels":["IN_APP"]}""")
        }
        assertEquals(HttpStatusCode.NoContent, forSelf.status)
        coVerify(exactly = 1) { notificationService.updatePreferences("alice", "comment_added", any()) }
    }

    @Test
    fun `websocket without a token is refused`() = testApplication {
        service()
        val ws = createClient { install(WebSockets) }
        assertFails { ws.webSocket("/ws/notifications/bob") { } }
        assertFails { ws.webSocket("/ws/notifications") { } }
        assertTrue(!webSocketManager.isUserConnected("bob"))
    }

    @Test
    fun `websocket for another user's path is closed`() = testApplication {
        service()
        val ws = createClient { install(WebSockets) }
        ws.webSocket("/ws/notifications/bob", request = { bearerAuth(token("alice")) }) {
            assertEquals(CloseReason.Codes.VIOLATED_POLICY.code, closeReason.await()?.code)
        }
        assertTrue(!webSocketManager.isUserConnected("bob"))
    }

    @Test
    fun `websocket subscribes the authenticated caller`() = testApplication {
        service()
        val ws = createClient { install(WebSockets) }
        ws.webSocket("/ws/notifications", request = { bearerAuth(token("alice")) }) {
            send(Frame.Text("ping"))
            assertEquals("pong", (incoming.receive() as Frame.Text).readText())
            assertTrue(webSocketManager.isUserConnected("alice"))
        }
    }
}
