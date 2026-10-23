package com.otterworks.notification.routes

import com.auth0.jwt.JWT
import com.auth0.jwt.algorithms.Algorithm
import com.otterworks.notification.auth.configureAuthentication
import com.otterworks.notification.configurePlugins
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.request.bearerAuth
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.put
import io.ktor.client.request.delete
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.server.application.install
import io.ktor.server.testing.ApplicationTestBuilder
import io.ktor.server.testing.testApplication
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import org.koin.core.context.stopKoin
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import java.util.Date
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class RoutesAuthTest {

    private val secret = "test-secret-that-is-long-enough-for-hs256-signing"
    private val service = mockk<NotificationService>(relaxed = true)

    @BeforeTest
    @AfterTest
    fun resetKoin() {
        stopKoin()
    }

    private fun token(
        sub: String,
        type: String = "access",
        key: String = secret,
        expiresAt: Date = Date(System.currentTimeMillis() + 60_000),
    ): String = JWT.create()
        .withSubject(sub)
        .withClaim("type", type)
        .withExpiresAt(expiresAt)
        .sign(Algorithm.HMAC256(key))

    private fun app(block: suspend ApplicationTestBuilder.() -> Unit) = testApplication {
        application {
            configurePlugins(
                AppConfig(
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
                    jwtSecret = secret,
                )
            )
            configureAuthentication(secret)
            install(Koin) {
                modules(module {
                    single { service }
                    single { mockk<WebSocketManager>(relaxed = true) }
                })
            }
            configureRouting(PrometheusMeterRegistry(PrometheusConfig.DEFAULT))
        }
        block()
    }

    @Test
    fun `requests without a valid access token are rejected`() = app {
        val anon = client.get("/api/v1/notifications?user_id=victim") { header("X-User-ID", "victim") }
        assertEquals(HttpStatusCode.Unauthorized, anon.status)

        val forged = client.get("/api/v1/notifications") { bearerAuth(token("victim", key = "wrong-secret")) }
        assertEquals(HttpStatusCode.Unauthorized, forged.status)

        val refresh = client.get("/api/v1/notifications") { bearerAuth(token("victim", type = "refresh")) }
        assertEquals(HttpStatusCode.Unauthorized, refresh.status)

        val expired = client.get("/api/v1/notifications") {
            bearerAuth(token("victim", expiresAt = Date(System.currentTimeMillis() - 60_000)))
        }
        assertEquals(HttpStatusCode.Unauthorized, expired.status)

        val prefs = client.put("/api/v1/preferences") {
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"victim","eventType":"file_shared","channels":[]}""")
        }
        assertEquals(HttpStatusCode.Unauthorized, prefs.status)

        assertEquals(HttpStatusCode.OK, client.get("/health").status)
        coVerify(exactly = 0) { service.getNotifications(any(), any(), any()) }
        coVerify(exactly = 0) { service.updatePreferences(any(), any(), any()) }
    }

    @Test
    fun `identity comes from the token, not the header or query`() = app {
        coEvery { service.getNotifications("alice", 1, 20) } returns Pair(emptyList(), 0)
        coEvery { service.getUnreadCount("alice") } returns 2

        val list = client.get("/api/v1/notifications?user_id=victim") {
            bearerAuth(token("alice"))
            header("X-User-ID", "victim")
        }
        assertEquals(HttpStatusCode.OK, list.status)

        val unread = client.get("/api/v1/notifications/unread-count?user_id=victim") { bearerAuth(token("alice")) }
        assertTrue(unread.bodyAsText().contains("\"userId\":\"alice\""))

        client.put("/api/v1/notifications/read-all?user_id=victim") { bearerAuth(token("alice")) }

        coVerify { service.getNotifications("alice", 1, 20) }
        coVerify { service.markAllAsRead("alice") }
        coVerify(exactly = 0) { service.getNotifications("victim", any(), any()) }
        coVerify(exactly = 0) { service.markAllAsRead("victim") }
    }

    @Test
    fun `preference updates ignore the body userId`() = app {
        coEvery { service.getPreferences("alice") } returns NotificationPreference(userId = "alice")

        val put = client.put("/api/v1/preferences") {
            bearerAuth(token("alice"))
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"victim","eventType":"file_shared","channels":["IN_APP"]}""")
        }
        assertEquals(HttpStatusCode.NoContent, put.status)
        coVerify { service.updatePreferences("alice", "file_shared", any()) }
        coVerify(exactly = 0) { service.updatePreferences("victim", any(), any()) }

        client.get("/api/v1/preferences?user_id=victim") { bearerAuth(token("alice")) }
        coVerify { service.getPreferences("alice") }
        coVerify(exactly = 0) { service.getPreferences("victim") }
    }

    @Test
    fun `by-id operations are scoped to the caller`() = app {
        val owned = Notification(
            id = "n-1",
            userId = "alice",
            type = "file_shared",
            title = "t",
            message = "m",
            createdAt = "2024-01-01T00:00:00Z",
        )
        coEvery { service.getNotificationById("n-1", "alice") } returns owned
        coEvery { service.getNotificationById("n-1", "mallory") } returns null
        coEvery { service.markAsRead("n-1", "alice") } returns true
        coEvery { service.markAsRead("n-1", "mallory") } returns false
        coEvery { service.deleteNotification("n-1", "alice") } returns true
        coEvery { service.deleteNotification("n-1", "mallory") } returns false

        assertEquals(HttpStatusCode.OK, client.get("/api/v1/notifications/n-1") { bearerAuth(token("alice")) }.status)
        assertEquals(HttpStatusCode.NotFound, client.get("/api/v1/notifications/n-1") { bearerAuth(token("mallory")) }.status)
        assertEquals(HttpStatusCode.NotFound, client.put("/api/v1/notifications/n-1/read") { bearerAuth(token("mallory")) }.status)
        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/n-1") { bearerAuth(token("mallory")) }.status)
        assertEquals(HttpStatusCode.NoContent, client.put("/api/v1/notifications/n-1/read") { bearerAuth(token("alice")) }.status)
        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/n-1") { bearerAuth(token("alice")) }.status)

        assertEquals(HttpStatusCode.Unauthorized, client.delete("/api/v1/notifications/n-1").status)
    }
}
