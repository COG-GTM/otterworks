package com.otterworks.notification.routes

import com.otterworks.notification.configurePlugins
import com.otterworks.notification.model.Notification
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.put
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpStatusCode
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
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class RoutesTest {

    private val notificationService = mockk<NotificationService>(relaxed = true)
    private val webSocketManager = mockk<WebSocketManager>(relaxed = true)

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    private fun withApp(block: suspend ApplicationTestBuilder.() -> Unit) = testApplication {
        application {
            configurePlugins()
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

    private val userIdRequired =
        """{"error":"user_id is required (via X-User-ID header or query parameter)"}"""
    private val notFound = """{"error":"Notification not found"}"""

    @Test
    fun `user-scoped routes reject a missing or blank user id`() = withApp {
        val responses = listOf(
            client.get("/api/v1/notifications"),
            client.get("/api/v1/notifications/unread-count") { header("X-User-ID", " ") },
            client.put("/api/v1/notifications/read-all"),
            client.get("/api/v1/preferences"),
        )
        responses.forEach {
            assertEquals(HttpStatusCode.BadRequest, it.status)
            assertEquals(userIdRequired, it.bodyAsText())
        }
    }

    @Test
    fun `user id comes from X-User-ID header or user_id query parameter`() = withApp {
        coEvery { notificationService.getUnreadCount("header-user") } returns 3
        coEvery { notificationService.markAllAsRead("query-user") } returns 2

        val unread = client.get("/api/v1/notifications/unread-count") { header("X-User-ID", "header-user") }
        assertEquals("""{"userId":"header-user","unreadCount":3}""", unread.bodyAsText())

        val readAll = client.put("/api/v1/notifications/read-all?user_id=query-user")
        assertEquals("""{"markedCount":2}""", readAll.bodyAsText())
    }

    @Test
    fun `list notifications paginates`() = withApp {
        coEvery { notificationService.getNotifications("u1", 2, 5) } returns (emptyList<Notification>() to 11)

        val response = client.get("/api/v1/notifications?page=2&page_size=5") { header("X-User-ID", "u1") }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("""{"data":[],"total":11,"page":2,"pageSize":5,"hasMore":true}""", response.bodyAsText())
    }

    @Test
    fun `id routes return 404 when the notification does not exist`() = withApp {
        coEvery { notificationService.getNotificationById("missing") } returns null
        coEvery { notificationService.markAsRead("missing") } returns false
        coEvery { notificationService.deleteNotification("missing") } returns false

        listOf(
            client.get("/api/v1/notifications/missing"),
            client.put("/api/v1/notifications/missing/read"),
            client.delete("/api/v1/notifications/missing"),
        ).forEach {
            assertEquals(HttpStatusCode.NotFound, it.status)
            assertEquals(notFound, it.bodyAsText())
        }
    }

    @Test
    fun `id routes succeed when the notification exists`() = withApp {
        coEvery { notificationService.getNotificationById("n1") } returns Notification(
            id = "n1", userId = "u1", type = "file_shared", title = "t", message = "m", createdAt = "now",
        )
        coEvery { notificationService.markAsRead("n1") } returns true
        coEvery { notificationService.deleteNotification("n1") } returns true

        val fetched = client.get("/api/v1/notifications/n1")
        assertEquals(HttpStatusCode.OK, fetched.status)
        assertTrue(fetched.bodyAsText().contains("\"id\":\"n1\""))
        assertEquals(HttpStatusCode.NoContent, client.put("/api/v1/notifications/n1/read").status)
        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/n1").status)
        coVerify { notificationService.markAsRead("n1") }
        coVerify { notificationService.deleteNotification("n1") }
    }
}
