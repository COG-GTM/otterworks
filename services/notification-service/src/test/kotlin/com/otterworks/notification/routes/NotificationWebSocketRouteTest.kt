package com.otterworks.notification.routes

import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.configurePlugins
import com.otterworks.notification.plugins.configureMonitoring
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.plugins.websocket.WebSockets as ClientWebSockets
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.server.application.Application
import io.ktor.server.application.install
import io.ktor.server.testing.testApplication
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import io.mockk.mockk
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeoutOrNull
import org.koin.dsl.module
import org.koin.ktor.plugin.Koin
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class NotificationWebSocketRouteTest {

    private val notificationService = mockk<NotificationService>(relaxed = true)
    private val webSocketManager = WebSocketManager()

    private val config = AppConfig(
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
    )

    @AfterTest
    fun tearDown() {
        org.koin.core.context.stopKoin()
    }

    private fun Application.testModule() {
        val registry = configureMonitoring()
        configurePlugins(config)
        install(Koin) {
            modules(
                module {
                    single { notificationService }
                    single { webSocketManager }
                },
            )
        }
        configureRouting(registry)
    }

    @Test
    fun `a websocket client is registered for its user and answers ping with pong`() = testApplication {
        application { testModule() }
        val wsClient = createClient { install(ClientWebSockets) }

        wsClient.webSocket("/ws/notifications/user-1") {
            send(Frame.Text("ping"))
            assertEquals("pong", (incoming.receive() as Frame.Text).readText())
            assertTrue(webSocketManager.isUserConnected("user-1"))

            send(Frame.Text("hello"))
        }

        // the server drops the connection in its own coroutine once the close frame lands
        withTimeoutOrNull(10_000) {
            while (webSocketManager.isUserConnected("user-1")) {
                delay(10)
            }
        }
        assertFalse(webSocketManager.isUserConnected("user-1"))
    }
}
