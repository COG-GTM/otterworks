package com.otterworks.notification.routes

import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.configurePlugins
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.repository.NotificationRepository
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.request.get
import io.ktor.client.request.header
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
import io.mockk.slot
import org.koin.core.context.stopKoin
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class PreferencesRoutesTest {

    private val repository = mockk<NotificationRepository>(relaxed = true)
    private val service = NotificationService(
        repository = repository,
        emailSender = mockk(relaxed = true),
        webSocketManager = mockk(relaxed = true),
        meterRegistry = null,
    )

    init {
        coEvery { repository.getPreferences(any()) } answers { NotificationPreference(userId = firstArg()) }
    }

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    private fun withApp(block: suspend ApplicationTestBuilder.() -> Unit) = testApplication {
        application {
            configurePlugins(AppConfig.load())
            install(Koin) {
                modules(
                    module {
                        single { service }
                        single { mockk<WebSocketManager>(relaxed = true) }
                    }
                )
            }
            configureRouting(PrometheusMeterRegistry(PrometheusConfig.DEFAULT))
        }
        block()
    }

    private suspend fun ApplicationTestBuilder.putPreferences(body: String, userId: String? = ATTACKER) =
        client.put("/api/v1/preferences") {
            userId?.let { header("X-User-ID", it) }
            contentType(ContentType.Application.Json)
            setBody(body)
        }

    @Test
    fun `PUT rejects a body userId that differs from the authenticated user`() = withApp {
        val response = putPreferences("""{"userId":"$VICTIM","eventType":"file_shared","channels":[]}""")

        assertEquals(HttpStatusCode.Forbidden, response.status)
        coVerify(exactly = 0) { repository.getPreferences(VICTIM) }
        coVerify(exactly = 0) { repository.savePreferences(any()) }
    }

    @Test
    fun `PUT updates the authenticated user's preferences when body userId is omitted`() = withApp {
        val saved = slot<NotificationPreference>()
        coEvery { repository.savePreferences(capture(saved)) } returns Unit

        val response = putPreferences("""{"eventType":"document_edited","channels":["EMAIL"]}""")

        assertEquals(HttpStatusCode.NoContent, response.status)
        assertEquals(ATTACKER, saved.captured.userId)
        assertEquals(listOf(DeliveryChannel.EMAIL), saved.captured.channels["document_edited"])
    }

    @Test
    fun `PUT accepts a body userId that matches the authenticated user`() = withApp {
        val saved = slot<NotificationPreference>()
        coEvery { repository.savePreferences(capture(saved)) } returns Unit

        val response = putPreferences("""{"userId":"$ATTACKER","eventType":"file_shared","channels":["IN_APP"]}""")

        assertEquals(HttpStatusCode.NoContent, response.status)
        assertEquals(ATTACKER, saved.captured.userId)
    }

    @Test
    fun `PUT without X-User-ID is unauthorized`() = withApp {
        val response = putPreferences(
            """{"userId":"$VICTIM","eventType":"file_shared","channels":[]}""",
            userId = null,
        )

        assertEquals(HttpStatusCode.Unauthorized, response.status)
        coVerify(exactly = 0) { repository.savePreferences(any()) }
    }

    @Test
    fun `PUT rejects unknown event types`() = withApp {
        val response = putPreferences("""{"eventType":"arbitrary_key","channels":["EMAIL"]}""")

        assertEquals(HttpStatusCode.BadRequest, response.status)
        coVerify(exactly = 0) { repository.savePreferences(any()) }
    }

    @Test
    fun `PUT rejects a malformed body with 400`() = withApp {
        val response = putPreferences("""{"eventType":"file_shared","channels":["CARRIER_PIGEON"]}""")

        assertEquals(HttpStatusCode.BadRequest, response.status)
        coVerify(exactly = 0) { repository.savePreferences(any()) }
    }

    @Test
    fun `GET returns the authenticated user's preferences`() = withApp {
        val response = client.get("/api/v1/preferences") { header("X-User-ID", ATTACKER) }

        assertEquals(HttpStatusCode.OK, response.status)
        assertTrue(response.bodyAsText().contains("\"userId\":\"$ATTACKER\""))
        coVerify(exactly = 1) { repository.getPreferences(ATTACKER) }
    }

    @Test
    fun `GET rejects a user_id query parameter for another user`() = withApp {
        val response = client.get("/api/v1/preferences?user_id=$VICTIM") { header("X-User-ID", ATTACKER) }

        assertEquals(HttpStatusCode.Forbidden, response.status)
        coVerify(exactly = 0) { repository.getPreferences(any()) }
    }

    @Test
    fun `GET without X-User-ID is unauthorized even with user_id`() = withApp {
        val response = client.get("/api/v1/preferences?user_id=$VICTIM")

        assertEquals(HttpStatusCode.Unauthorized, response.status)
        coVerify(exactly = 0) { repository.getPreferences(any()) }
    }

    private companion object {
        const val ATTACKER = "11111111-1111-1111-1111-111111111111"
        const val VICTIM = "22222222-2222-2222-2222-222222222222"
    }
}
