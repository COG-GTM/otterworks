package com.otterworks.notification

import aws.sdk.kotlin.services.dynamodb.DynamoDbClient
import aws.sdk.kotlin.services.ses.SesClient
import aws.sdk.kotlin.services.sqs.SqsClient
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.consumer.SqsConsumer
import com.otterworks.notification.plugins.configureMonitoring
import com.otterworks.notification.repository.NotificationRepository
import com.otterworks.notification.service.EmailSender
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.websocket.WebSocketManager
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.options
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.call
import io.ktor.server.response.respond
import io.ktor.server.routing.get
import io.ktor.server.routing.routing
import io.ktor.server.testing.testApplication
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

@Serializable
private data class Echo(val value: String)

class ApplicationTest {

    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "http://localhost:4566/000000000000/test-queue",
        snsTopicArn = "arn:aws:sns:us-east-1:000000000000:test-topic",
        dynamoDbTableNotifications = "test-notifications",
        dynamoDbTablePreferences = "test-preferences",
        sesFromEmail = "notifications@otterworks.io",
        sqsPollIntervalMs = 1000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    @Test
    fun `configureMonitoring exposes JVM and request metrics`() = testApplication {
        lateinit var registry: PrometheusMeterRegistry
        application {
            registry = configureMonitoring()
            routing { get("/ping") { call.respond("pong") } }
        }

        client.get("/ping")
        val scrape = registry.scrape()

        assertTrue(scrape.contains("jvm_memory_used_bytes"))
        assertTrue(scrape.contains("ktor_http_server_requests_seconds"))
    }

    @Test
    fun `configurePlugins negotiates JSON leniently`() = testApplication {
        application {
            configurePlugins(config)
            routing { get("/echo") { call.respond(Echo("hello")) } }
        }

        val response = client.get("/echo")

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("""{"value":"hello"}""", response.bodyAsText())
    }

    @Test
    fun `configurePlugins allows the web app and admin dashboard origins`() = testApplication {
        application {
            configurePlugins(config)
            routing { get("/echo") { call.respond(Echo("hello")) } }
        }

        val allowed = client.options("/echo") {
            header(HttpHeaders.Origin, "http://localhost:3000")
            header(HttpHeaders.AccessControlRequestMethod, HttpMethod.Put.value)
        }
        val rejected = client.get("/echo") { header(HttpHeaders.Origin, "http://evil.example") }

        assertEquals(HttpStatusCode.OK, allowed.status)
        assertEquals(HttpStatusCode.Forbidden, rejected.status)
    }

    @Test
    fun `configureDependencyInjection wires the object graph`() = testApplication {
        application {
            val registry = PrometheusMeterRegistry(PrometheusConfig.DEFAULT)
            configureDependencyInjection(config, registry)

            val koin = GlobalContext.get()
            assertSame(config, koin.get<AppConfig>())
            assertSame(registry, koin.get<MeterRegistry>())
            assertNotNull(koin.get<SqsClient>())
            assertNotNull(koin.get<DynamoDbClient>())
            assertNotNull(koin.get<SesClient>())
            assertNotNull(koin.get<NotificationRepository>())
            assertNotNull(koin.get<EmailSender>())
            assertNotNull(koin.get<NotificationService>())
            assertNotNull(koin.get<SqsConsumer>())
            assertSame(koin.get<WebSocketManager>(), koin.get<WebSocketManager>())
        }

        client.get("/")
    }

    @Test
    fun `configureDependencyInjection honours a custom AWS endpoint`() = testApplication {
        val localstack = config.copy(awsEndpointUrl = "http://localstack:4566")
        application {
            configureDependencyInjection(localstack, PrometheusMeterRegistry(PrometheusConfig.DEFAULT))

            val koin = GlobalContext.get()
            assertNotNull(koin.get<SqsClient>())
            assertNotNull(koin.get<DynamoDbClient>())
            assertNotNull(koin.get<SesClient>())
        }

        client.get("/")
    }
}
