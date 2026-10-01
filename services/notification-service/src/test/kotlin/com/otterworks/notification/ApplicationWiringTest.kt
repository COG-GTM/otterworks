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
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.Application
import io.ktor.server.routing.get
import io.ktor.server.routing.routing
import io.ktor.server.testing.testApplication
import io.micrometer.core.instrument.MeterRegistry
import io.micrometer.prometheus.PrometheusMeterRegistry
import org.koin.ktor.ext.inject
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

class ApplicationWiringTest {

    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = "http://localhost:4566",
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

    private fun Application.wiring(): PrometheusMeterRegistry {
        val registry = configureMonitoring()
        configurePlugins(config)
        configureDependencyInjection(config, registry)
        return registry
    }

    @Test
    fun `dependency injection builds the full notification object graph`() = testApplication {
        application {
            wiring()

            val appConfig by inject<AppConfig>()
            val meterRegistry by inject<MeterRegistry>()
            val sqsClient by inject<SqsClient>()
            val dynamoDbClient by inject<DynamoDbClient>()
            val sesClient by inject<SesClient>()
            val webSocketManager by inject<WebSocketManager>()
            val repository by inject<NotificationRepository>()
            val emailSender by inject<EmailSender>()
            val notificationService by inject<NotificationService>()
            val sqsConsumer by inject<SqsConsumer>()

            assertSame(config, appConfig)
            assertNotNull(meterRegistry)
            assertNotNull(sqsClient)
            assertNotNull(dynamoDbClient)
            assertNotNull(sesClient)
            assertNotNull(repository)
            assertNotNull(emailSender)
            assertNotNull(notificationService)
            assertNotNull(sqsConsumer)
            assertSame(webSocketManager, inject<WebSocketManager>().value)
        }

        // Force the application (and therefore the Koin graph above) to be created.
        client.get("/does-not-exist")
    }

    @Test
    fun `monitoring exposes JVM metrics through the prometheus registry`() = testApplication {
        lateinit var registry: PrometheusMeterRegistry
        application { registry = wiring() }

        client.get("/does-not-exist")

        val scrape = registry.scrape()
        assertTrue(scrape.contains("jvm_memory_used_bytes"))
        assertTrue(scrape.contains("process_uptime_seconds"))
        assertTrue(scrape.contains("jvm_threads_live_threads"))
    }

    @Test
    fun `CORS allows the web app origin and the mutating methods it uses`() = testApplication {
        application { wiring() }

        val response = client.options("/health") {
            header(HttpHeaders.Origin, "http://localhost:3000")
            header(HttpHeaders.AccessControlRequestMethod, "PUT")
            header(HttpHeaders.AccessControlRequestHeaders, HttpHeaders.ContentType)
        }

        assertEquals(HttpStatusCode.OK, response.status)
        assertEquals("http://localhost:3000", response.headers[HttpHeaders.AccessControlAllowOrigin])
    }

    @Test
    fun `CORS rejects an origin that is not the web app or admin dashboard`() = testApplication {
        application { wiring() }

        val response = client.options("/health") {
            header(HttpHeaders.Origin, "http://evil.example.com")
            header(HttpHeaders.AccessControlRequestMethod, "PUT")
        }

        assertEquals(HttpStatusCode.Forbidden, response.status)
    }

    @Test
    fun `unhandled failures are mapped to a JSON internal server error`() = testApplication {
        application {
            wiring()
            routing {
                get("/boom") { throw IllegalStateException("kaboom") }
            }
        }

        val response = client.get("/boom")

        assertEquals(HttpStatusCode.InternalServerError, response.status)
        assertTrue(response.bodyAsText().contains("Internal server error"))
    }
}
