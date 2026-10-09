package com.otterworks.notification.routes

import com.auth0.jwt.JWT
import com.auth0.jwt.algorithms.Algorithm
import com.otterworks.notification.auth.configureAuthentication
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.HttpClient
import io.ktor.client.plugins.websocket.WebSockets
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.client.request.bearerAuth
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
import io.ktor.serialization.kotlinx.json.json
import io.ktor.server.application.install
import io.ktor.server.plugins.contentnegotiation.ContentNegotiation
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
import io.mockk.verify
import org.koin.core.context.stopKoin
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import java.util.Date
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import io.ktor.server.websocket.WebSockets as ServerWebSockets

class RoutesAuthTest {

    private val secret = "otterworks-local-dev-jwt-secret-change-me-in-production"
    private val notificationService = mockk<NotificationService>(relaxed = true)
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    private fun token(
        subject: String,
        algorithm: Algorithm = Algorithm.HMAC384(secret),
        type: String = "access",
        expiresAt: Date = Date(System.currentTimeMillis() + 60_000),
    ): String = JWT.create()
        .withSubject(subject)
        .withClaim("type", type)
        .withExpiresAt(expiresAt)
        .sign(algorithm)

    private fun authApp(block: suspend ApplicationTestBuilder.() -> Unit) = testApplication {
        application {
            install(ContentNegotiation) { json() }
            install(ServerWebSockets)
            configureAuthentication(secret)
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
        block()
    }

    private fun ApplicationTestBuilder.wsClient(): HttpClient = createClient { install(WebSockets) }

    private fun notification(id: String, userId: String) = Notification(
        id = id,
        userId = userId,
        type = "file_shared",
        title = "t",
        message = "m",
        createdAt = "2024-01-01T00:00:00Z",
    )

    @Test
    fun `health stays public`() = authApp {
        assertEquals(HttpStatusCode.OK, client.get("/health").status)
    }

    @Test
    fun `spoofed X-User-ID or user_id without a token is rejected`() = authApp {
        assertEquals(
            HttpStatusCode.Unauthorized,
            client.get("/api/v1/notifications") { header("X-User-ID", "victim") }.status,
        )
        assertEquals(HttpStatusCode.Unauthorized, client.get("/api/v1/notifications?user_id=victim").status)
        assertEquals(HttpStatusCode.Unauthorized, client.get("/api/v1/notifications/unread-count?user_id=victim").status)
        assertEquals(HttpStatusCode.Unauthorized, client.put("/api/v1/notifications/read-all?user_id=victim").status)
        assertEquals(HttpStatusCode.Unauthorized, client.get("/api/v1/preferences?user_id=victim").status)
        assertEquals(HttpStatusCode.Unauthorized, client.delete("/api/v1/notifications/n-1").status)
        coVerify(exactly = 0) { notificationService.getNotifications(any(), any(), any()) }
        coVerify(exactly = 0) { notificationService.markAllAsRead(any()) }
    }

    @Test
    fun `identity comes from the token subject, not the header or query`() = authApp {
        coEvery { notificationService.getNotifications("alice", 1, 20) } returns Pair(emptyList(), 0)
        val response = client.get("/api/v1/notifications?user_id=victim") {
            bearerAuth(token("alice"))
            header("X-User-ID", "victim")
        }
        assertEquals(HttpStatusCode.OK, response.status)
        coVerify(exactly = 1) { notificationService.getNotifications("alice", 1, 20) }
        coVerify(exactly = 0) { notificationService.getNotifications("victim", any(), any()) }
    }

    @Test
    fun `tokens signed with HS256, HS384 and HS512 are accepted`() = authApp {
        coEvery { notificationService.getUnreadCount("alice") } returns 2
        for (algorithm in listOf(Algorithm.HMAC256(secret), Algorithm.HMAC384(secret), Algorithm.HMAC512(secret))) {
            val response = client.get("/api/v1/notifications/unread-count") { bearerAuth(token("alice", algorithm)) }
            assertEquals(HttpStatusCode.OK, response.status, algorithm.name)
            assertTrue(response.bodyAsText().contains("\"userId\":\"alice\""))
        }
    }

    @Test
    fun `forged, expired, refresh and unsigned tokens are rejected`() = authApp {
        val rejected = listOf(
            token("alice", Algorithm.HMAC256("not-the-secret")),
            token("alice", expiresAt = Date(System.currentTimeMillis() - 60_000)),
            token("alice", type = "refresh"),
            JWT.create().withSubject("alice").sign(Algorithm.none()),
            "garbage",
        )
        for (bad in rejected) {
            assertEquals(
                HttpStatusCode.Unauthorized,
                client.get("/api/v1/notifications") { bearerAuth(bad) }.status,
            )
        }
    }

    @Test
    fun `another user's notification cannot be read, marked or deleted`() = authApp {
        coEvery { notificationService.getNotificationForUser("n-1", "attacker") } returns null
        coEvery { notificationService.markAsRead("n-1", "attacker") } returns false
        coEvery { notificationService.deleteNotification("n-1", "attacker") } returns false
        val bearer = token("attacker")
        assertEquals(HttpStatusCode.NotFound, client.get("/api/v1/notifications/n-1") { bearerAuth(bearer) }.status)
        assertEquals(HttpStatusCode.NotFound, client.put("/api/v1/notifications/n-1/read") { bearerAuth(bearer) }.status)
        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/n-1") { bearerAuth(bearer) }.status)
    }

    @Test
    fun `owner can read and delete their notification`() = authApp {
        coEvery { notificationService.getNotificationForUser("n-1", "alice") } returns notification("n-1", "alice")
        coEvery { notificationService.deleteNotification("n-1", "alice") } returns true
        val bearer = token("alice")
        assertEquals(HttpStatusCode.OK, client.get("/api/v1/notifications/n-1") { bearerAuth(bearer) }.status)
        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/n-1") { bearerAuth(bearer) }.status)
    }

    @Test
    fun `preferences are read and written for the token subject only`() = authApp {
        coEvery { notificationService.getPreferences("alice") } returns NotificationPreference(userId = "alice")
        val bearer = token("alice")
        assertEquals(
            HttpStatusCode.OK,
            client.get("/api/v1/preferences?user_id=victim") { bearerAuth(bearer) }.status,
        )
        coVerify(exactly = 0) { notificationService.getPreferences("victim") }

        val forbidden = client.put("/api/v1/preferences") {
            bearerAuth(bearer)
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"victim","eventType":"file_shared","channels":["EMAIL"]}""")
        }
        assertEquals(HttpStatusCode.Forbidden, forbidden.status)

        val own = client.put("/api/v1/preferences") {
            bearerAuth(bearer)
            contentType(ContentType.Application.Json)
            setBody("""{"eventType":"file_shared","channels":["EMAIL"]}""")
        }
        assertEquals(HttpStatusCode.NoContent, own.status)
        coVerify(exactly = 0) { notificationService.updatePreferences("victim", any(), any()) }
        coVerify(exactly = 1) { notificationService.updatePreferences("alice", "file_shared", any()) }
    }

    @Test
    fun `websocket without a token is refused before upgrade`() = authApp {
        assertFailsWith<Exception> {
            wsClient().webSocket("/ws/notifications/victim") { }
        }
        verify(exactly = 0) { webSocketManager.addConnection(any(), any()) }
    }

    @Test
    fun `websocket for another user's id is closed without subscribing`() = authApp {
        wsClient().webSocket("/ws/notifications/victim", request = { bearerAuth(token("attacker")) }) {
            val reason = closeReason.await()
            assertEquals(CloseReason.Codes.VIOLATED_POLICY.code, reason?.code)
        }
        verify(exactly = 0) { webSocketManager.addConnection(any(), any()) }
    }

    @Test
    fun `websocket accepts the token as a bearer subprotocol`() = authApp {
        wsClient().webSocket(
            "/ws/notifications/alice",
            request = { header(HttpHeaders.SecWebSocketProtocol, "bearer, ${token("alice")}") },
        ) {
            send(Frame.Text("ping"))
            assertEquals("pong", (incoming.receive() as Frame.Text).readText())
        }
        verify(exactly = 1) { webSocketManager.addConnection("alice", any()) }
    }

    @Test
    fun `websocket accepts an Authorization header`() = authApp {
        wsClient().webSocket("/ws/notifications/alice", request = { bearerAuth(token("alice")) }) {
            send(Frame.Text("ping"))
            assertEquals("pong", (incoming.receive() as Frame.Text).readText())
        }
        verify(exactly = 1) { webSocketManager.addConnection("alice", any()) }
    }
}
