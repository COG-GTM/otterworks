package com.otterworks.notification.routes

import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
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
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.just
import io.mockk.mockk
import io.mockk.runs
import org.koin.core.context.stopKoin
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class NotificationCallerScopeRoutesTest {

    private val notificationService = mockk<NotificationService>()
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    private fun withRoutes(block: suspend ApplicationTestBuilder.() -> Unit) = testApplication {
        application {
            install(ContentNegotiation) { json() }
            install(WebSockets)
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

    private suspend fun assertUnauthorized(response: HttpResponse) {
        assertEquals(HttpStatusCode.Unauthorized, response.status)
        assertTrue(response.bodyAsText().contains("X-User-ID"))
    }

    @Test
    fun `preference update applies to the caller, not a body userId`() = withRoutes {
        coEvery { notificationService.updatePreferences(any(), any(), any()) } just runs

        val response = client.put("/api/v1/preferences") {
            header("X-User-ID", "alice")
            contentType(ContentType.Application.Json)
            setBody("""{"eventType":"file_shared","channels":["IN_APP"]}""")
        }

        assertEquals(HttpStatusCode.NoContent, response.status)
        coVerify(exactly = 1) {
            notificationService.updatePreferences("alice", "file_shared", listOf(DeliveryChannel.IN_APP))
        }
    }

    @Test
    fun `preference update accepts the caller's own userId in the body`() = withRoutes {
        coEvery { notificationService.updatePreferences(any(), any(), any()) } just runs

        val response = client.put("/api/v1/preferences") {
            header("X-User-ID", "alice")
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"alice","eventType":"file_shared","channels":[]}""")
        }

        assertEquals(HttpStatusCode.NoContent, response.status)
        coVerify(exactly = 1) { notificationService.updatePreferences("alice", "file_shared", emptyList()) }
    }

    @Test
    fun `preference update for another user is rejected`() = withRoutes {
        val response = client.put("/api/v1/preferences") {
            header("X-User-ID", "mallory")
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"alice","eventType":"file_shared","channels":[]}""")
        }

        assertEquals(HttpStatusCode.Forbidden, response.status)
        coVerify(exactly = 0) { notificationService.updatePreferences(any(), any(), any()) }
    }

    @Test
    fun `preference update requires the gateway identity header`() = withRoutes {
        assertUnauthorized(
            client.put("/api/v1/preferences") {
                contentType(ContentType.Application.Json)
                setBody("""{"userId":"alice","eventType":"file_shared","channels":[]}""")
            }
        )
        coVerify(exactly = 0) { notificationService.updatePreferences(any(), any(), any()) }
    }

    @Test
    fun `preference read ignores the user_id query parameter`() = withRoutes {
        coEvery { notificationService.getPreferences("mallory") } returns NotificationPreference(userId = "mallory")

        val response = client.get("/api/v1/preferences?user_id=alice") { header("X-User-ID", "mallory") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("mallory"))
        coVerify(exactly = 0) { notificationService.getPreferences("alice") }
        assertUnauthorized(client.get("/api/v1/preferences?user_id=alice"))
    }

    @Test
    fun `list, unread-count and read-all use only the caller id`() = withRoutes {
        coEvery { notificationService.getNotifications("mallory", 1, 20) } returns Pair(emptyList(), 0)
        coEvery { notificationService.getUnreadCount("mallory") } returns 0
        coEvery { notificationService.markAllAsRead("mallory") } returns 0

        assertEquals(
            HttpStatusCode.OK,
            client.get("/api/v1/notifications?user_id=alice") { header("X-User-ID", "mallory") }.status,
        )
        assertEquals(
            HttpStatusCode.OK,
            client.get("/api/v1/notifications/unread-count?user_id=alice") { header("X-User-ID", "mallory") }.status,
        )
        assertEquals(
            HttpStatusCode.OK,
            client.put("/api/v1/notifications/read-all?user_id=alice") { header("X-User-ID", "mallory") }.status,
        )

        coVerify(exactly = 0) { notificationService.getNotifications("alice", any(), any()) }
        coVerify(exactly = 0) { notificationService.getUnreadCount("alice") }
        coVerify(exactly = 0) { notificationService.markAllAsRead("alice") }
    }

    @Test
    fun `list, unread-count and read-all require the gateway identity header`() = withRoutes {
        assertUnauthorized(client.get("/api/v1/notifications?user_id=alice"))
        assertUnauthorized(client.get("/api/v1/notifications/unread-count?user_id=alice"))
        assertUnauthorized(client.put("/api/v1/notifications/read-all?user_id=alice"))
        coVerify(exactly = 0) { notificationService.markAllAsRead(any()) }
    }
}
