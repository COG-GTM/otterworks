package com.otterworks.notification.routes

import com.otterworks.notification.model.Notification
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.put
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpStatusCode
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
import kotlin.test.assertTrue

class NotificationByIdRoutesTest {

    private val notificationService = mockk<NotificationService>()
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)

    private val notification = Notification(
        id = "n-1",
        userId = "victim",
        type = "file_shared",
        title = "File Shared With You",
        message = "secret.pdf",
        createdAt = "2024-01-01T00:00:00Z",
    )

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

    private suspend fun assertUnauthorizedWithoutService(response: HttpResponse) {
        assertEquals(HttpStatusCode.Unauthorized, response.status)
        assertTrue(response.bodyAsText().contains("X-User-ID"))
    }

    @Test
    fun `get by id returns the notification to its owner`() = withRoutes {
        coEvery { notificationService.getNotificationById("n-1", "victim") } returns notification

        val response = client.get("/api/v1/notifications/n-1") { header("X-User-ID", "victim") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("secret.pdf"))
    }

    @Test
    fun `get by id is 404 for another user's notification`() = withRoutes {
        coEvery { notificationService.getNotificationById("n-1", "attacker") } returns null

        val response = client.get("/api/v1/notifications/n-1") { header("X-User-ID", "attacker") }

        assertEquals(HttpStatusCode.NotFound, response.status)
        coVerify(exactly = 1) { notificationService.getNotificationById("n-1", "attacker") }
    }

    @Test
    fun `get by id requires the gateway identity header`() = withRoutes {
        assertUnauthorizedWithoutService(client.get("/api/v1/notifications/n-1"))
        assertUnauthorizedWithoutService(client.get("/api/v1/notifications/n-1?user_id=victim"))
        assertUnauthorizedWithoutService(client.get("/api/v1/notifications/n-1") { header("X-User-ID", " ") })
        coVerify(exactly = 0) { notificationService.getNotificationById(any(), any()) }
    }

    @Test
    fun `mark read passes the caller id and is 404 when not owned`() = withRoutes {
        coEvery { notificationService.markAsRead("n-1", "victim") } returns true
        coEvery { notificationService.markAsRead("n-1", "attacker") } returns false

        val owner = client.put("/api/v1/notifications/n-1/read") { header("X-User-ID", "victim") }
        val other = client.put("/api/v1/notifications/n-1/read") { header("X-User-ID", "attacker") }

        assertEquals(HttpStatusCode.NoContent, owner.status)
        assertEquals(HttpStatusCode.NotFound, other.status)
    }

    @Test
    fun `mark read requires the gateway identity header`() = withRoutes {
        assertUnauthorizedWithoutService(client.put("/api/v1/notifications/n-1/read?user_id=victim"))
        coVerify(exactly = 0) { notificationService.markAsRead(any(), any()) }
    }

    @Test
    fun `delete passes the caller id and is 404 when not owned`() = withRoutes {
        coEvery { notificationService.deleteNotification("n-1", "victim") } returns true
        coEvery { notificationService.deleteNotification("n-1", "attacker") } returns false

        val owner = client.delete("/api/v1/notifications/n-1") { header("X-User-ID", "victim") }
        val other = client.delete("/api/v1/notifications/n-1") { header("X-User-ID", "attacker") }

        assertEquals(HttpStatusCode.NoContent, owner.status)
        assertEquals(HttpStatusCode.NotFound, other.status)
    }

    @Test
    fun `delete requires the gateway identity header`() = withRoutes {
        assertUnauthorizedWithoutService(client.delete("/api/v1/notifications/n-1?user_id=victim"))
        coVerify(exactly = 0) { notificationService.deleteNotification(any(), any()) }
    }
}
