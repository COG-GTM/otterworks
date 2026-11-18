package com.otterworks.notification.alerts

import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.testConfig
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class AlertPublisherDeliveryTest {

    private data class Received(val path: String, val secret: String?, val body: String)

    private val received = LinkedBlockingQueue<Received>()
    private var status = 202
    private val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
        createContext("/") { ex ->
            received.add(
                Received(ex.requestURI.path, ex.requestHeaders.getFirst("X-Alert-Secret"), ex.requestBody.readBytes().decodeToString())
            )
            ex.sendResponseHeaders(status, -1)
            ex.close()
        }
        start()
    }
    private val baseUrl = "http://127.0.0.1:${server.address.port}/"

    @AfterTest
    fun tearDown() = server.stop(0)

    private fun next() = received.poll(5, TimeUnit.SECONDS)

    @Test
    fun `posts alert with secret header to ingest endpoint`() {
        AlertPublisher(baseUrl, "s3cret").notifyConsumerFailure("QueueDoesNotExist")

        val req = assertNotNull(next())
        assertEquals("/api/v1/admin/alerts/ingest", req.path)
        assertEquals("s3cret", req.secret)
        assertTrue(req.body.contains("QueueDoesNotExist"))
    }

    @Test
    fun `rate limits repeated alerts within the interval`() {
        val publisher = AlertPublisher(baseUrl, null)
        publisher.notifyConsumerFailure("first")
        publisher.notifyConsumerFailure("second")

        val req = assertNotNull(next())
        assertNull(req.secret)
        assertTrue(req.body.contains("first"))
        assertNull(received.poll(300, TimeUnit.MILLISECONDS))
    }

    @Test
    fun `zero interval sends every alert and tolerates rejections`() {
        status = 500
        val publisher = AlertPublisher(baseUrl, " ", minIntervalMs = 0)
        publisher.notifyConsumerFailure("a")
        assertNotNull(next())
        Thread.sleep(5)
        publisher.notifyConsumerFailure("b")
        val second = assertNotNull(next())
        assertNull(second.secret)
        Thread.sleep(200)
    }

    @Test
    fun `config constructor uses admin url and secret`() {
        val config: AppConfig = testConfig(adminServiceUrl = baseUrl).copy(alertWebhookSecret = "cfg")
        AlertPublisher(config).notifyConsumerFailure("x")
        assertEquals("cfg", assertNotNull(next()).secret)
        Thread.sleep(200)
    }
}
