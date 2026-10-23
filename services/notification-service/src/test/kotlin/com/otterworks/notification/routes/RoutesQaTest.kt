package com.otterworks.notification.routes

import com.otterworks.notification.configurePlugins
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.patch
import io.ktor.client.request.post
import io.ktor.client.request.put
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
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Ignore
import org.koin.core.context.stopKoin
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Route-level tests for the notification REST API with a mocked service layer. */
class RoutesQaTest {

    private val service = mockk<NotificationService>(relaxed = true)

    @BeforeTest
    fun resetKoin() {
        stopKoin()
    }

    @AfterTest
    fun tearDownKoin() {
        stopKoin()
    }

    private fun notification(id: String, userId: String, read: Boolean = false) = Notification(
        id = id,
        userId = userId,
        type = "file_shared",
        title = "File Shared With You",
        message = "A file has been shared with you",
        resourceId = "file-1",
        resourceType = "file",
        read = read,
        createdAt = "2026-01-01T00:00:00Z",
    )

    private fun withApp(block: suspend ApplicationTestBuilder.() -> Unit) = testApplication {
        application {
            configurePlugins()
            install(Koin) {
                modules(module {
                    single { service }
                    single { WebSocketManager() }
                })
            }
            configureRouting(PrometheusMeterRegistry(PrometheusConfig.DEFAULT))
        }
        block()
    }

    private fun json(text: String) = Json.parseToJsonElement(text).jsonObject

    @Test
    fun `health returns healthy`() = withApp {
        val res = client.get("/health")
        assertEquals(HttpStatusCode.OK, res.status)
        assertEquals("healthy", json(res.bodyAsText())["status"]!!.jsonPrimitive.content)
    }

    @Test
    fun `metrics endpoint is exposed as text`() = withApp {
        val res = client.get("/metrics")
        assertEquals(HttpStatusCode.OK, res.status)
        assertTrue(res.headers["Content-Type"]!!.startsWith("text/plain"))
    }

    @Test
    fun `list without user id is 400`() = withApp {
        val res = client.get("/api/v1/notifications")
        assertEquals(HttpStatusCode.BadRequest, res.status)
        assertTrue(res.bodyAsText().contains("user_id is required"))
    }

    @Test
    fun `list with blank header is 400`() = withApp {
        val res = client.get("/api/v1/notifications") { header("X-User-ID", "  ") }
        assertEquals(HttpStatusCode.BadRequest, res.status)
    }

    @Test
    fun `list prefers X-User-ID header over query parameter`() = withApp {
        coEvery { service.getNotifications("header-user", 1, 20) } returns Pair(emptyList(), 0)
        val res = client.get("/api/v1/notifications?user_id=query-user") { header("X-User-ID", "header-user") }
        assertEquals(HttpStatusCode.OK, res.status)
        coVerify { service.getNotifications("header-user", 1, 20) }
        coVerify(exactly = 0) { service.getNotifications("query-user", any(), any()) }
    }

    @Test
    fun `list returns paginated envelope with hasMore`() = withApp {
        coEvery { service.getNotifications("u1", 2, 2) } returns
            Pair(listOf(notification("n3", "u1"), notification("n4", "u1")), 5)
        val res = client.get("/api/v1/notifications?page=2&page_size=2") { header("X-User-ID", "u1") }
        assertEquals(HttpStatusCode.OK, res.status)
        val body = json(res.bodyAsText())
        assertEquals(2, body["data"]!!.jsonArray.size)
        assertEquals(5, body["total"]!!.jsonPrimitive.int)
        assertEquals(2, body["page"]!!.jsonPrimitive.int)
        assertEquals(2, body["pageSize"]!!.jsonPrimitive.int)
        assertTrue(body["hasMore"]!!.jsonPrimitive.boolean)
    }

    @Test
    fun `list last page has hasMore false`() = withApp {
        coEvery { service.getNotifications("u1", 3, 2) } returns Pair(listOf(notification("n5", "u1")), 5)
        val res = client.get("/api/v1/notifications?page=3&page_size=2") { header("X-User-ID", "u1") }
        assertEquals(false, json(res.bodyAsText())["hasMore"]!!.jsonPrimitive.boolean)
    }

    @Test
    fun `list falls back to defaults on non-numeric paging params`() = withApp {
        coEvery { service.getNotifications("u1", 1, 20) } returns Pair(emptyList(), 0)
        val res = client.get("/api/v1/notifications?page=abc&page_size=xyz") { header("X-User-ID", "u1") }
        assertEquals(HttpStatusCode.OK, res.status)
        coVerify { service.getNotifications("u1", 1, 20) }
    }

    @Ignore("FINDING NS-4: page<=0 / page_size<=0 are passed straight to the repository (no validation) and crash with 500")
    @Test
    fun `list rejects non-positive page with 400`() = withApp {
        coEvery { service.getNotifications("u1", 0, 20) } throws IllegalArgumentException("Requested element count -20 is less than zero.")
        val res = client.get("/api/v1/notifications?page=0") { header("X-User-ID", "u1") }
        assertEquals(HttpStatusCode.BadRequest, res.status)
    }

    @Test
    fun `unread-count requires user and returns count`() = withApp {
        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/notifications/unread-count").status)
        coEvery { service.getUnreadCount("u1") } returns 3
        val res = client.get("/api/v1/notifications/unread-count") { header("X-User-ID", "u1") }
        val body = json(res.bodyAsText())
        assertEquals("u1", body["userId"]!!.jsonPrimitive.content)
        assertEquals(3, body["unreadCount"]!!.jsonPrimitive.int)
    }

    @Test
    fun `get by id returns 404 when missing`() = withApp {
        coEvery { service.getNotificationById("missing") } returns null
        val res = client.get("/api/v1/notifications/missing") { header("X-User-ID", "u1") }
        assertEquals(HttpStatusCode.NotFound, res.status)
    }

    @Test
    fun `get by id returns owner's notification`() = withApp {
        coEvery { service.getNotificationById("n1") } returns notification("n1", "u1")
        val res = client.get("/api/v1/notifications/n1") { header("X-User-ID", "u1") }
        assertEquals(HttpStatusCode.OK, res.status)
        assertEquals("n1", json(res.bodyAsText())["id"]!!.jsonPrimitive.content)
    }

    @Ignore("FINDING NS-1: GET /api/v1/notifications/{id} has no ownership check - any user can read another user's notification")
    @Test
    fun `get by id hides another user's notification`() = withApp {
        coEvery { service.getNotificationById("n1") } returns notification("n1", "owner")
        val res = client.get("/api/v1/notifications/n1") { header("X-User-ID", "intruder") }
        assertTrue(res.status == HttpStatusCode.NotFound || res.status == HttpStatusCode.Forbidden)
    }

    @Test
    fun `mark read returns 204 on success and 404 when missing`() = withApp {
        coEvery { service.getNotificationById("n1") } returns notification("n1", "u1")
        coEvery { service.markAsRead("n1") } returns true
        coEvery { service.markAsRead("missing") } returns false
        assertEquals(HttpStatusCode.NoContent, client.put("/api/v1/notifications/n1/read") { header("X-User-ID", "u1") }.status)
        assertEquals(HttpStatusCode.NotFound, client.put("/api/v1/notifications/missing/read") { header("X-User-ID", "u1") }.status)
    }

    @Ignore("FINDING NS-2: PUT /api/v1/notifications/{id}/read has no ownership check - any user can mark another user's notification read")
    @Test
    fun `mark read refuses another user's notification`() = withApp {
        coEvery { service.getNotificationById("n1") } returns notification("n1", "owner")
        coEvery { service.markAsRead("n1") } returns true
        val res = client.put("/api/v1/notifications/n1/read") { header("X-User-ID", "intruder") }
        assertTrue(res.status == HttpStatusCode.NotFound || res.status == HttpStatusCode.Forbidden)
        coVerify(exactly = 0) { service.markAsRead("n1") }
    }

    @Test
    fun `PATCH read and POST read-all are not routed (client-app uses these verbs)`() = withApp {
        // Documents FINDING NS-6: the web client calls PATCH /{id}/read and POST /read-all,
        // but the service only exposes PUT for both.
        val patch = client.patch("/api/v1/notifications/n1/read") { header("X-User-ID", "u1") }
        val post = client.post("/api/v1/notifications/read-all") { header("X-User-ID", "u1") }
        assertTrue(patch.status == HttpStatusCode.MethodNotAllowed || patch.status == HttpStatusCode.NotFound)
        assertTrue(post.status == HttpStatusCode.MethodNotAllowed || post.status == HttpStatusCode.NotFound)
    }

    @Test
    fun `read-all requires user and returns marked count`() = withApp {
        assertEquals(HttpStatusCode.BadRequest, client.put("/api/v1/notifications/read-all").status)
        coEvery { service.markAllAsRead("u1") } returns 4
        val res = client.put("/api/v1/notifications/read-all") { header("X-User-ID", "u1") }
        assertEquals(HttpStatusCode.OK, res.status)
        assertEquals(4, json(res.bodyAsText())["markedCount"]!!.jsonPrimitive.int)
    }

    @Test
    fun `delete returns 204 on success and 404 when missing`() = withApp {
        coEvery { service.getNotificationById("n1") } returns notification("n1", "u1")
        coEvery { service.deleteNotification("n1") } returns true
        coEvery { service.deleteNotification("missing") } returns false
        assertEquals(HttpStatusCode.NoContent, client.delete("/api/v1/notifications/n1") { header("X-User-ID", "u1") }.status)
        assertEquals(HttpStatusCode.NotFound, client.delete("/api/v1/notifications/missing") { header("X-User-ID", "u1") }.status)
    }

    @Ignore("FINDING NS-3: DELETE /api/v1/notifications/{id} has no ownership check - any user can delete another user's notification")
    @Test
    fun `delete refuses another user's notification`() = withApp {
        coEvery { service.getNotificationById("n1") } returns notification("n1", "owner")
        coEvery { service.deleteNotification("n1") } returns true
        val res = client.delete("/api/v1/notifications/n1") { header("X-User-ID", "intruder") }
        assertTrue(res.status == HttpStatusCode.NotFound || res.status == HttpStatusCode.Forbidden)
        coVerify(exactly = 0) { service.deleteNotification("n1") }
    }

    @Test
    fun `get preferences requires user and returns channel map`() = withApp {
        assertEquals(HttpStatusCode.BadRequest, client.get("/api/v1/preferences").status)
        coEvery { service.getPreferences("u1") } returns NotificationPreference(userId = "u1")
        val res = client.get("/api/v1/preferences") { header("X-User-ID", "u1") }
        assertEquals(HttpStatusCode.OK, res.status)
        val body = json(res.bodyAsText())
        assertEquals("u1", body["userId"]!!.jsonPrimitive.content)
        assertTrue(body["channels"]!!.jsonObject.containsKey("file_shared"))
    }

    @Test
    fun `put preferences updates and returns 204`() = withApp {
        val res = client.put("/api/v1/preferences") {
            header("X-User-ID", "u1")
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"u1","eventType":"document_edited","channels":["IN_APP","EMAIL"]}""")
        }
        assertEquals(HttpStatusCode.NoContent, res.status)
        coVerify { service.updatePreferences("u1", "document_edited", listOf(DeliveryChannel.IN_APP, DeliveryChannel.EMAIL)) }
    }

    @Ignore("FINDING NS-7: PUT /api/v1/preferences with a malformed body or unknown channel returns 500 instead of 400")
    @Test
    fun `put preferences with unknown channel is 400`() = withApp {
        val res = client.put("/api/v1/preferences") {
            header("X-User-ID", "u1")
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"u1","eventType":"document_edited","channels":["SMS"]}""")
        }
        assertEquals(HttpStatusCode.BadRequest, res.status)
    }

    @Ignore("FINDING NS-5: PUT /api/v1/preferences trusts body.userId and ignores X-User-ID - any user can rewrite another user's preferences")
    @Test
    fun `put preferences cannot target another user`() = withApp {
        val res = client.put("/api/v1/preferences") {
            header("X-User-ID", "intruder")
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"victim","eventType":"file_shared","channels":[]}""")
        }
        coVerify(exactly = 0) { service.updatePreferences("victim", any(), any()) }
        assertTrue(res.status.value in setOf(204, 403))
    }
}
