package com.otterworks.notification.routes

import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import io.ktor.server.application.install
import io.ktor.server.plugins.contentnegotiation.ContentNegotiation
import io.ktor.server.testing.ApplicationTestBuilder
import io.ktor.server.testing.testApplication
import io.ktor.server.websocket.WebSockets
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

class RoutesTest {

    private val notificationService = mockk<NotificationService>(relaxed = true)

    // The Koin Ktor plugin registers a global Koin context that outlives each testApplication.
    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    private fun ApplicationTestBuilder.setUp() {
        application {
            install(ContentNegotiation) { json() }
            install(WebSockets)
            install(Koin) {
                modules(
                    module {
                        single { notificationService }
                        single { mockk<WebSocketManager>(relaxed = true) }
                    },
                )
            }
            configureRouting(PrometheusMeterRegistry(PrometheusConfig.DEFAULT))
        }
    }

    @Test
    fun `user-scoped routes ignore the user_id query parameter without X-User-ID`() = testApplication {
        setUp()
        for (path in listOf("/api/v1/notifications", "/api/v1/notifications/unread-count", "/api/v1/preferences")) {
            val response = client.get("$path?user_id=victim")
            assertEquals(HttpStatusCode.Unauthorized, response.status, path)
        }
        assertEquals(HttpStatusCode.Unauthorized, client.put("/api/v1/notifications/read-all?user_id=victim").status)

        coVerify(exactly = 0) { notificationService.getNotifications(any(), any(), any()) }
        coVerify(exactly = 0) { notificationService.getUnreadCount(any()) }
        coVerify(exactly = 0) { notificationService.getPreferences(any()) }
        coVerify(exactly = 0) { notificationService.markAllAsRead(any()) }
    }

    @Test
    fun `X-User-ID header wins over the user_id query parameter`() = testApplication {
        setUp()
        coEvery { notificationService.getUnreadCount("alice") } returns 3
        coEvery { notificationService.markAllAsRead("alice") } returns 2
        coEvery { notificationService.getNotifications("alice", 1, 20) } returns (emptyList<Notification>() to 0)
        coEvery { notificationService.getPreferences("alice") } returns NotificationPreference(userId = "alice")

        assertEquals(
            HttpStatusCode.OK,
            client.get("/api/v1/notifications/unread-count?user_id=victim") { header("X-User-ID", "alice") }.status,
        )
        assertEquals(
            HttpStatusCode.OK,
            client.get("/api/v1/notifications?user_id=victim") { header("X-User-ID", "alice") }.status,
        )
        assertEquals(
            HttpStatusCode.OK,
            client.get("/api/v1/preferences?user_id=victim") { header("X-User-ID", "alice") }.status,
        )
        assertEquals(
            HttpStatusCode.OK,
            client.put("/api/v1/notifications/read-all?user_id=victim") { header("X-User-ID", "alice") }.status,
        )

        coVerify(exactly = 0) { notificationService.getUnreadCount("victim") }
        coVerify(exactly = 0) { notificationService.getNotifications("victim", any(), any()) }
        coVerify(exactly = 0) { notificationService.getPreferences("victim") }
        coVerify(exactly = 0) { notificationService.markAllAsRead("victim") }
    }

    @Test
    fun `preferences update is bound to X-User-ID`() = testApplication {
        setUp()
        val body = """{"userId":"victim","eventType":"file_shared","channels":["EMAIL"]}"""

        val anonymous = client.put("/api/v1/preferences") {
            contentType(ContentType.Application.Json)
            setBody(body)
        }
        assertEquals(HttpStatusCode.Unauthorized, anonymous.status)

        val mismatched = client.put("/api/v1/preferences") {
            header("X-User-ID", "alice")
            contentType(ContentType.Application.Json)
            setBody(body)
        }
        assertEquals(HttpStatusCode.Forbidden, mismatched.status)
        coVerify(exactly = 0) { notificationService.updatePreferences(any(), any(), any()) }

        val own = client.put("/api/v1/preferences") {
            header("X-User-ID", "alice")
            contentType(ContentType.Application.Json)
            setBody("""{"eventType":"file_shared","channels":["EMAIL"]}""")
        }
        assertEquals(HttpStatusCode.NoContent, own.status)
        coVerify(exactly = 1) { notificationService.updatePreferences("alice", "file_shared", any()) }
    }
}
