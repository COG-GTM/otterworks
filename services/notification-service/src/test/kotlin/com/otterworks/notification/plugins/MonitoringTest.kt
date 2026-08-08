package com.otterworks.notification.plugins

import io.ktor.client.request.get
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.call
import io.ktor.server.response.respondText
import io.ktor.server.routing.get
import io.ktor.server.routing.routing
import io.ktor.server.testing.testApplication
import io.micrometer.prometheus.PrometheusMeterRegistry
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class MonitoringTest {

    @Test
    fun `configureMonitoring registers JVM binders and records http server metrics`() = testApplication {
        var registry: PrometheusMeterRegistry? = null
        application {
            registry = configureMonitoring()
            routing {
                get("/ping") { call.respondText("pong") }
            }
        }

        assertEquals(HttpStatusCode.OK, client.get("/ping").status)

        val scraped = assertNotNull(registry).scrape()
        assertTrue(scraped.contains("jvm_memory_used_bytes"), "JVM memory binder should be registered")
        assertTrue(scraped.contains("jvm_threads_live_threads"), "JVM thread binder should be registered")
        assertTrue(scraped.contains("process_uptime_seconds"), "uptime binder should be registered")
        assertTrue(
            scraped.contains("ktor_http_server_requests_seconds"),
            "MicrometerMetrics should record the served request: $scraped",
        )
        assertEquals("pong", client.get("/ping").bodyAsText())
    }
}
