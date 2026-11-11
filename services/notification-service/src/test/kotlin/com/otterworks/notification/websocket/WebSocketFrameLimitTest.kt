package com.otterworks.notification.websocket

import com.otterworks.notification.MAX_WEBSOCKET_FRAME_SIZE
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.configurePlugins
import io.ktor.client.HttpClient
import io.ktor.client.engine.cio.CIO
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.server.engine.embeddedServer
import io.ktor.server.netty.Netty
import io.ktor.server.routing.routing
import io.ktor.server.websocket.webSocket
import io.ktor.websocket.CloseReason
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import java.net.ServerSocket
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import io.ktor.client.plugins.websocket.WebSockets as ClientWebSockets

/** The notification WebSocket must not buffer arbitrarily large client frames. */
class WebSocketFrameLimitTest {

    private val config = AppConfig(
        port = 0,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "",
        snsTopicArn = "",
        dynamoDbTableNotifications = "",
        dynamoDbTablePreferences = "",
        sesFromEmail = "",
        sqsPollIntervalMs = 1000L,
        sqsMaxMessages = 1,
        sqsWaitTimeSeconds = 0,
    )

    private fun withPingServer(block: suspend HttpClient.(port: Int) -> Unit) {
        val port = ServerSocket(0).use { it.localPort }
        val server = embeddedServer(Netty, port = port, host = "127.0.0.1") {
            configurePlugins(config)
            routing {
                webSocket("/ws/ping") {
                    for (frame in incoming) {
                        if (frame is Frame.Text && frame.readText() == "ping") {
                            send(Frame.Text("pong"))
                        }
                    }
                }
            }
        }.start(wait = false)
        val client = HttpClient(CIO) { install(ClientWebSockets) }
        try {
            runBlocking { withTimeout(20_000) { client.block(port) } }
        } finally {
            client.close()
            server.stop(0, 0)
        }
    }

    @Test
    fun maxFrameSizeIsBounded() {
        assertTrue(MAX_WEBSOCKET_FRAME_SIZE in 1..(1024L * 1024L))
    }

    @Test
    fun smallFramesAreStillHandled() = withPingServer { port ->
        webSocket(host = "127.0.0.1", port = port, path = "/ws/ping") {
            send(Frame.Text("ping"))
            val reply = incoming.receive()
            assertEquals("pong", (reply as Frame.Text).readText())
        }
    }

    @Test
    fun oversizedFrameClosesConnectionWithTooBig() = withPingServer { port ->
        webSocket(host = "127.0.0.1", port = port, path = "/ws/ping") {
            send(Frame.Text("x".repeat((MAX_WEBSOCKET_FRAME_SIZE + 1).toInt())))
            val reason = closeReason.await()
            assertEquals(CloseReason.Codes.TOO_BIG.code, reason?.code)
        }
    }
}
