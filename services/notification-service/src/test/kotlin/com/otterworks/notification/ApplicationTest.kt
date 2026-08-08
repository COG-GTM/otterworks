package com.otterworks.notification

import aws.sdk.kotlin.services.dynamodb.DynamoDbClient
import aws.sdk.kotlin.services.ses.SesClient
import aws.sdk.kotlin.services.sqs.SqsClient
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.consumer.SqsConsumer
import com.otterworks.notification.repository.NotificationRepository
import com.otterworks.notification.service.EmailSender
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.request.get
import io.ktor.client.request.options
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.server.application.call
import io.ktor.server.request.receive
import io.ktor.server.response.respond
import io.ktor.server.response.respondText
import io.ktor.server.routing.get
import io.ktor.server.routing.post
import io.ktor.server.routing.routing
import io.ktor.server.testing.testApplication
import io.ktor.server.websocket.webSocket
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import io.ktor.client.plugins.websocket.WebSockets as ClientWebSockets
import io.ktor.client.plugins.websocket.webSocket as clientWebSocket
import io.micrometer.core.instrument.MeterRegistry
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import kotlinx.serialization.Serializable
import org.koin.core.context.GlobalContext
import org.koin.core.context.stopKoin
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

class ApplicationTest {

    @Serializable
    private data class Echo(val value: String)

    @AfterTest
    fun tearDown() {
        if (GlobalContext.getOrNull() != null) stopKoin()
    }

    // ---------- configurePlugins ----------

    @Test
    fun `content negotiation ignores unknown keys and does not pretty-print`() = testApplication {
        application {
            configurePlugins(testConfig())
            routing {
                post("/echo") { call.respond(call.receive<Echo>()) }
            }
        }

        val response = client.post("/echo") {
            contentType(ContentType.Application.Json)
            setBody("""{"value":"hello","unknown":true}""")
        }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("""{"value":"hello"}""", response.bodyAsText())
    }

    @Test
    fun `CORS allows the web app and the admin dashboard but not a foreign origin`() = testApplication {
        application {
            configurePlugins(testConfig())
            routing {
                get("/health") { call.respond(mapOf("status" to "healthy")) }
            }
        }

        val allowed = client.get("/health") { header(HttpHeaders.Origin, "http://localhost:3000") }
        val admin = client.get("/health") { header(HttpHeaders.Origin, "http://localhost:4200") }
        val foreign = client.get("/health") { header(HttpHeaders.Origin, "http://evil.example.com") }

        assertEquals(HttpStatusCode.OK, allowed.status)
        assertEquals(
            "http://localhost:3000",
            allowed.headers[HttpHeaders.AccessControlAllowOrigin],
        )
        assertEquals(HttpStatusCode.OK, admin.status)
        assertEquals(HttpStatusCode.Forbidden, foreign.status)
    }

    @Test
    fun `CORS pre-flight advertises the mutating methods the web app needs`() = testApplication {
        application {
            configurePlugins(testConfig())
            routing {
                get("/health") { call.respond(mapOf("status" to "healthy")) }
            }
        }

        val preflight = client.options("/health") {
            header(HttpHeaders.Origin, "http://localhost:3000")
            header(HttpHeaders.AccessControlRequestMethod, "PUT")
            header(HttpHeaders.AccessControlRequestHeaders, HttpHeaders.Authorization)
        }

        assertEquals(HttpStatusCode.OK, preflight.status)
        val allowedMethods = preflight.headers[HttpHeaders.AccessControlAllowMethods].orEmpty()
        assertTrue(allowedMethods.contains("PUT"), allowedMethods)
        assertTrue(allowedMethods.contains("DELETE"), allowedMethods)
        assertTrue(allowedMethods.contains("PATCH"), allowedMethods)
    }

    @Test
    fun `websocket support is installed so ws routes can be served`() = testApplication {
        application {
            configurePlugins(testConfig())
            routing {
                webSocket("/ws/echo") {
                    val received = (incoming.receive() as Frame.Text).readText()
                    send(Frame.Text("echo:$received"))
                }
            }
        }
        val wsClient = createClient { install(ClientWebSockets) }

        wsClient.clientWebSocket("/ws/echo") {
            send(Frame.Text("hello"))
            assertEquals("echo:hello", (incoming.receive() as Frame.Text).readText())
        }
    }

    @Test
    fun `an unhandled exception is reported as a 500 json error`() = testApplication {
        application {
            configurePlugins(testConfig())
            routing {
                get("/boom") { throw IllegalStateException("kaboom") }
            }
        }

        val response = client.get("/boom")

        assertEquals(HttpStatusCode.InternalServerError, response.status)
        assertEquals("""{"error":"Internal server error"}""", response.bodyAsText())
    }

    // ---------- configureDependencyInjection ----------

    private fun assertGraphResolves(config: AppConfig) = testApplication {
        val registry = PrometheusMeterRegistry(PrometheusConfig.DEFAULT)
        application {
            configureDependencyInjection(config, registry)
            routing { get("/health") { call.respondText("healthy") } }
        }

        assertEquals(HttpStatusCode.OK, client.get("/health").status)

        val koin = assertNotNull(GlobalContext.getOrNull())
        assertSame(config, koin.get<AppConfig>())
        assertSame(registry, koin.get<MeterRegistry>())

        val sqsClient = koin.get<SqsClient>()
        val dynamoDbClient = koin.get<DynamoDbClient>()
        val sesClient = koin.get<SesClient>()
        assertEquals(config.awsRegion, sqsClient.config.region)
        assertEquals(config.awsRegion, dynamoDbClient.config.region)
        assertEquals(config.awsRegion, sesClient.config.region)

        assertNotNull(koin.get<NotificationRepository>())
        assertNotNull(koin.get<EmailSender>())
        assertNotNull(koin.get<NotificationService>())
        assertNotNull(koin.get<SqsConsumer>())

        // Every collaborator is a singleton, so a websocket registered on one route is
        // visible to the notification service pushing on another.
        assertSame(koin.get<WebSocketManager>(), koin.get<WebSocketManager>())
        assertSame(koin.get<NotificationService>(), koin.get<NotificationService>())
        assertSame(koin.get<SqsClient>(), sqsClient)

        sqsClient.close()
        dynamoDbClient.close()
        sesClient.close()
    }

    @Test
    fun `the dependency graph resolves against real AWS endpoints`() {
        assertGraphResolves(testConfig())
    }

    @Test
    fun `the dependency graph resolves against an endpoint override such as LocalStack`() {
        assertGraphResolves(testConfig(awsEndpointUrl = "http://localhost:4566"))
    }
}
