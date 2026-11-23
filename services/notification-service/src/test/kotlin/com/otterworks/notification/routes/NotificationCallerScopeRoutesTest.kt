package com.otterworks.notification.routes

import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.request.HttpRequestBuilder
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

    private companion object {
        const val VICTIM = "victim"
        const val ATTACKER = "attacker"
        const val USER_HEADER = "X-User-ID"
        const val PREFERENCES = "/api/v1/preferences"
    }

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
        assertTrue(response.bodyAsText().contains(USER_HEADER))
    }

    @Test
    fun `preferences update targets the caller and ignores the body userId`() = withRoutes {
        coEvery { notificationService.updatePreferences(any(), any(), any()) } just runs

        val response = client.put(PREFERENCES) {
            header(USER_HEADER, ATTACKER)
            contentType(ContentType.Application.Json)
            setBody("""{"userId":"$VICTIM","eventType":"file_shared","channels":[]}""")
        }

        assertEquals(HttpStatusCode.NoContent, response.status)
        coVerify(exactly = 1) { notificationService.updatePreferences(ATTACKER, "file_shared", emptyList()) }
        coVerify(exactly = 0) { notificationService.updatePreferences(VICTIM, any(), any()) }
    }

    @Test
    fun `preferences update accepts a body without userId`() = withRoutes {
        coEvery { notificationService.updatePreferences(any(), any(), any()) } just runs

        val response = client.put(PREFERENCES) {
            header(USER_HEADER, VICTIM)
            contentType(ContentType.Application.Json)
            setBody("""{"eventType":"comment_added","channels":["EMAIL","IN_APP"]}""")
        }

        assertEquals(HttpStatusCode.NoContent, response.status)
        coVerify(exactly = 1) {
            notificationService.updatePreferences(
                VICTIM,
                "comment_added",
                listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP),
            )
        }
    }

    @Test
    fun `preferences update requires the gateway identity header`() = withRoutes {
        assertUnauthorized(
            client.put(PREFERENCES) {
                contentType(ContentType.Application.Json)
                setBody("""{"userId":"$VICTIM","eventType":"file_shared","channels":[]}""")
            }
        )
        coVerify(exactly = 0) { notificationService.updatePreferences(any(), any(), any()) }
    }

    @Test
    fun `preferences read uses the header and ignores the user_id query`() = withRoutes {
        coEvery { notificationService.getPreferences(ATTACKER) } returns NotificationPreference(userId = ATTACKER)

        val response = client.get("$PREFERENCES?user_id=$VICTIM") { header(USER_HEADER, ATTACKER) }

        assertEquals(HttpStatusCode.OK, response.status)
        coVerify(exactly = 1) { notificationService.getPreferences(ATTACKER) }
        coVerify(exactly = 0) { notificationService.getPreferences(VICTIM) }
    }

    @Test
    fun `user_id query no longer substitutes for the identity header`() = withRoutes {
        assertUnauthorized(client.get("/api/v1/notifications?user_id=$VICTIM"))
        assertUnauthorized(client.get("/api/v1/notifications/unread-count?user_id=$VICTIM"))
        assertUnauthorized(client.put("/api/v1/notifications/read-all?user_id=$VICTIM"))
        assertUnauthorized(client.get("$PREFERENCES?user_id=$VICTIM"))
        assertUnauthorized(client.get("/api/v1/notifications") { header(USER_HEADER, " ") })

        coVerify(exactly = 0) { notificationService.getNotifications(any(), any(), any()) }
        coVerify(exactly = 0) { notificationService.getUnreadCount(any()) }
        coVerify(exactly = 0) { notificationService.markAllAsRead(any()) }
        coVerify(exactly = 0) { notificationService.getPreferences(any()) }
    }

    @Test
    fun `list endpoints are scoped to the header caller`() = withRoutes {
        coEvery { notificationService.getNotifications(ATTACKER, 1, 20) } returns (emptyList<Notification>() to 0)
        coEvery { notificationService.getUnreadCount(ATTACKER) } returns 0
        coEvery { notificationService.markAllAsRead(ATTACKER) } returns 0

        val asAttacker: HttpRequestBuilder.() -> Unit = { header(USER_HEADER, ATTACKER) }
        assertEquals(HttpStatusCode.OK, client.get("/api/v1/notifications?user_id=$VICTIM", asAttacker).status)
        assertEquals(HttpStatusCode.OK, client.get("/api/v1/notifications/unread-count?user_id=$VICTIM", asAttacker).status)
        assertEquals(HttpStatusCode.OK, client.put("/api/v1/notifications/read-all?user_id=$VICTIM", asAttacker).status)

        coVerify(exactly = 0) { notificationService.getNotifications(VICTIM, any(), any()) }
        coVerify(exactly = 0) { notificationService.getUnreadCount(VICTIM) }
        coVerify(exactly = 0) { notificationService.markAllAsRead(VICTIM) }
    }
}
