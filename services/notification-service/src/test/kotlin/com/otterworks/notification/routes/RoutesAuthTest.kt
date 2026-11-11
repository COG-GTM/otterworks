package com.otterworks.notification.routes

import com.auth0.jwt.JWT
import com.auth0.jwt.algorithms.Algorithm
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.configurePlugins
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
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
import org.koin.core.context.stopKoin
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import java.time.Instant
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import io.ktor.client.plugins.websocket.WebSockets as ClientWebSockets

class RoutesAuthTest {

    private val secret = "test-jwt-secret-that-is-at-least-48-bytes-long-000"
    private val notificationService = mockk<NotificationService>(relaxed = true)

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    private fun token(
        subject: String,
        signingSecret: String = secret,
        type: String = "access",
    ): String = JWT.create()
        .withSubject(subject)
        .withClaim("type", type)
        .withExpiresAt(Instant.now().plusSeconds(300))
        .sign(Algorithm.HMAC384(signingSecret))

    private fun withService(jwtSecret: String? = secret, block: suspend ApplicationTestBuilder.() -> Unit) =
        testApplication {
            application {
                configurePlugins(AppConfig.load().copy(jwtSecret = jwtSecret))
                install(Koin) {
                    modules(
                        module {
                            single { notificationService }
                            single { WebSocketManager() }
                            single { CallerIdentityResolver(jwtSecret) }
                        }
                    )
                }
                configureRouting(PrometheusMeterRegistry(PrometheusConfig.DEFAULT))
            }
            block()
        }

    @Test
    fun `list rejects user_id query and forged header without a token`() = withService {
        assertEquals(HttpStatusCode.Unauthorized, client.get("/api/v1/notifications?user_id=alice").status)
        assertEquals(
            HttpStatusCode.Unauthorized,
            client.get("/api/v1/notifications") { header("X-User-ID", "alice") }.status,
        )
        coVerify(exactly = 0) { notificationService.getNotifications(any(), any(), any()) }
    }

    @Test
    fun `list uses the token subject, not the user_id query`() = withService {
        coEvery { notificationService.getNotifications("mallory", 1, 20) } returns Pair(emptyList(), 0)

        val response = client.get("/api/v1/notifications?user_id=alice") {
            header(HttpHeaders.Authorization, "Bearer ${token("mallory")}")
        }

        assertEquals(HttpStatusCode.OK, response.status)
        coVerify { notificationService.getNotifications("mallory", 1, 20) }
        coVerify(exactly = 0) { notificationService.getNotifications("alice", any(), any()) }
    }

    @Test
    fun `X-User-ID that disagrees with the token is rejected`() = withService {
        val response = client.get("/api/v1/notifications/unread-count") {
            header(HttpHeaders.Authorization, "Bearer ${token("mallory")}")
            header("X-User-ID", "alice")
        }
        assertEquals(HttpStatusCode.Unauthorized, response.status)
    }

    @Test
    fun `tokens signed with another secret or refresh tokens are rejected`() = withService {
        val forged = client.get("/api/v1/preferences") {
            header(HttpHeaders.Authorization, "Bearer ${token("alice", signingSecret = "x".repeat(48))}")
        }
        val refresh = client.get("/api/v1/preferences") {
            header(HttpHeaders.Authorization, "Bearer ${token("alice", type = "refresh")}")
        }
        assertEquals(HttpStatusCode.Unauthorized, forged.status)
        assertEquals(HttpStatusCode.Unauthorized, refresh.status)
    }

    @Test
    fun `preferences update rejects another user's id in the body`() = withService {
        val response = client.put("/api/v1/preferences") {
            header(HttpHeaders.Authorization, "Bearer ${token("mallory")}")
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"alice","eventType":"file_shared","channels":[]}""")
        }

        assertEquals(HttpStatusCode.Forbidden, response.status)
        coVerify(exactly = 0) { notificationService.updatePreferences(any(), any(), any()) }
    }

    @Test
    fun `preferences update is saved under the caller`() = withService {
        val response = client.put("/api/v1/preferences") {
            header(HttpHeaders.Authorization, "Bearer ${token("alice")}")
            contentType(ContentType.Application.Json)
            setBody("""{"eventType":"file_shared","channels":["EMAIL"]}""")
        }

        assertEquals(HttpStatusCode.NoContent, response.status)
        coVerify { notificationService.updatePreferences("alice", "file_shared", listOf(DeliveryChannel.EMAIL)) }
    }

    @Test
    fun `get, mark-read and delete by id are scoped to the caller`() = withService {
        coEvery { notificationService.getNotificationById("n-1", "mallory") } returns null
        coEvery { notificationService.markAsRead("n-1", "mallory") } returns false
        coEvery { notificationService.deleteNotification("n-1", "mallory") } returns false
        val auth = "Bearer ${token("mallory")}"

        assertEquals(HttpStatusCode.NotFound, client.get("/api/v1/notifications/n-1") { header(HttpHeaders.Authorization, auth) }.status)
        assertEquals(HttpStatusCode.NotFound, client.put("/api/v1/notifications/n-1/read") { header(HttpHeaders.Authorization, auth) }.status)
        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/n-1") { header(HttpHeaders.Authorization, auth) }.status)

        coVerify { notificationService.getNotificationById("n-1", "mallory") }
        coVerify { notificationService.markAsRead("n-1", "mallory") }
        coVerify { notificationService.deleteNotification("n-1", "mallory") }
    }

    @Test
    fun `without a JWT secret the gateway header is the only identity source`() = withService(jwtSecret = null) {
        coEvery { notificationService.getPreferences("alice") } returns NotificationPreference(userId = "alice")

        assertEquals(HttpStatusCode.Unauthorized, client.get("/api/v1/preferences?user_id=alice").status)
        assertEquals(HttpStatusCode.OK, client.get("/api/v1/preferences") { header("X-User-ID", "alice") }.status)
        coVerify(exactly = 1) { notificationService.getPreferences("alice") }
    }

    @Test
    fun `websocket requires a token whose subject matches the path`() = withService {
        val wsClient = createClient { install(ClientWebSockets) }

        wsClient.webSocket("/ws/notifications/alice") {
            assertEquals(CloseReason.Codes.VIOLATED_POLICY.code, closeReason.await()?.code)
        }
        wsClient.webSocket("/ws/notifications/alice?access_token=${token("mallory")}") {
            assertEquals(CloseReason.Codes.VIOLATED_POLICY.code, closeReason.await()?.code)
        }
        wsClient.webSocket("/ws/notifications/alice?access_token=${token("alice")}") {
            send(Frame.Text("ping"))
            assertEquals("pong", (incoming.receive() as Frame.Text).readText())
        }
    }
}
