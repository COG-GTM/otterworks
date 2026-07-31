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
import kotlin.test.assertTrue

class MonitoringTest {

    @Test
    fun `configureMonitoring registers the JVM and system meter binders`() = testApplication {
        lateinit var registry: PrometheusMeterRegistry
        application {
            registry = configureMonitoring()
            routing { get("/ping") { call.respondText("pong") } }
        }

        assertEquals(HttpStatusCode.OK, client.get("/ping").status)

        val scrape = registry.scrape()
        assertTrue(scrape.contains("jvm_memory_used_bytes"), scrape.take(500))
        assertTrue(scrape.contains("jvm_threads_live_threads"), scrape.take(500))
        assertTrue(scrape.contains("jvm_classes_loaded_classes"), scrape.take(500))
        assertTrue(scrape.contains("process_uptime_seconds"), scrape.take(500))
        assertTrue(scrape.contains("system_cpu_count"), scrape.take(500))
    }

    @Test
    fun `configureMonitoring records ktor http server request metrics`() = testApplication {
        lateinit var registry: PrometheusMeterRegistry
        application {
            registry = configureMonitoring()
            routing { get("/ping") { call.respondText("pong") } }
        }

        assertEquals("pong", client.get("/ping").bodyAsText())

        val requestCount = registry.find("ktor.http.server.requests").timers().sumOf { it.count() }
        assertEquals(1L, requestCount)
    }
}
