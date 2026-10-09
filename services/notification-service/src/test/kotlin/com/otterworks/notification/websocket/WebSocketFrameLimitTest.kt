package com.otterworks.notification.websocket

import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.configurePlugins
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.server.routing.routing
import io.ktor.server.testing.testApplication
import io.ktor.server.websocket.webSocket
import io.ktor.websocket.CloseReason
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import kotlin.test.Test
import kotlin.test.assertEquals
import io.ktor.client.plugins.websocket.WebSockets as ClientWebSockets

class WebSocketFrameLimitTest {

    @Test
    fun `default frame cap is 64 KiB`() {
        assertEquals(64L * 1024, AppConfig.DEFAULT_WS_MAX_FRAME_BYTES)
    }

    @Test
    fun `oversized client frame closes the socket with TOO_BIG`() = testApplication {
        val config = AppConfig.load().copy(wsMaxFrameBytes = 1024)
        application {
            configurePlugins(config)
            routing {
                webSocket("/ws") {
                    for (frame in incoming) {
                        if (frame is Frame.Text && frame.readText() == "ping") {
                            send(Frame.Text("pong"))
                        }
                    }
                }
            }
        }
        val client = createClient { install(ClientWebSockets) }

        client.webSocket("/ws") {
            send(Frame.Text("ping"))
            assertEquals("pong", (incoming.receive() as Frame.Text).readText())

            send(Frame.Text("x".repeat(4 * 1024)))

            assertEquals(CloseReason.Codes.TOO_BIG.code, closeReason.await()?.code)
        }
    }
}
