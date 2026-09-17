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
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.call
import io.ktor.server.response.respondText
import io.ktor.server.routing.get
import io.ktor.server.routing.routing
import io.ktor.server.testing.testApplication
import io.micrometer.core.instrument.MeterRegistry
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import org.koin.core.Koin
import org.koin.core.context.stopKoin
import org.koin.ktor.ext.getKoin
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

class ApplicationTest {

    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        // Unroutable on purpose: no test may reach a real AWS endpoint.
        awsEndpointUrl = "http://localhost:1",
        sqsQueueUrl = "http://localhost:1/000000000000/test-queue",
        snsTopicArn = "arn:aws:sns:us-east-1:000000000000:test-topic",
        dynamoDbTableNotifications = "test-notifications",
        dynamoDbTablePreferences = "test-preferences",
        sesFromEmail = "test@otterworks.io",
        // Long enough that the consumer's error backoff never fires twice during a test.
        sqsPollIntervalMs = 600_000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 1,
    )

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    @Test
    fun `configurePlugins serializes responses and allows the web app origin`() = testApplication {
        application {
            configurePlugins(config)
            routing { get("/ok") { call.respondText("ok") } }
        }

        val preflight = client.options("/ok") {
            header(HttpHeaders.Origin, "http://localhost:3000")
            header(HttpHeaders.AccessControlRequestMethod, "PUT")
        }

        assertEquals(HttpStatusCode.OK, preflight.status)
        assertEquals(
            "http://localhost:3000",
            preflight.headers[HttpHeaders.AccessControlAllowOrigin],
        )
    }

    @Test
    fun `configurePlugins rejects a disallowed origin`() = testApplication {
        application {
            // Exercises the AppConfig.load() default argument as well.
            configurePlugins()
            routing { get("/ok") { call.respondText("ok") } }
        }

        val response = client.get("/ok") { header(HttpHeaders.Origin, "http://evil.example.com") }

        assertEquals(HttpStatusCode.Forbidden, response.status)
    }

    @Test
    fun `configurePlugins converts unhandled exceptions into a 500 payload`() = testApplication {
        application {
            configurePlugins(config)
            routing { get("/boom") { throw IllegalStateException("kaboom") } }
        }

        val response = client.get("/boom")

        assertEquals(HttpStatusCode.InternalServerError, response.status)
        assertTrue(response.bodyAsText().contains("Internal server error"), response.bodyAsText())
    }

    @Test
    fun `configureDependencyInjection wires every collaborator as a singleton`() = testApplication {
        val registry = PrometheusMeterRegistry(PrometheusConfig.DEFAULT)
        lateinit var koin: Koin
        application {
            configureDependencyInjection(config, registry)
            koin = getKoin()
            routing { get("/ok") { call.respondText("ok") } }
        }

        assertEquals(HttpStatusCode.OK, client.get("/ok").status)

        assertSame(config, koin.get<AppConfig>())
        assertSame(registry, koin.get<MeterRegistry>())

        val sqsClient = koin.get<SqsClient>()
        val dynamoDbClient = koin.get<DynamoDbClient>()
        val sesClient = koin.get<SesClient>()
        assertEquals("us-east-1", sqsClient.config.region)
        assertEquals("http://localhost:1", sqsClient.config.endpointUrl.toString())
        assertEquals("us-east-1", dynamoDbClient.config.region)
        assertEquals("us-east-1", sesClient.config.region)

        assertNotNull(koin.get<NotificationRepository>())
        assertNotNull(koin.get<EmailSender>())
        assertNotNull(koin.get<NotificationService>())
        assertNotNull(koin.get<SqsConsumer>())
        assertSame(koin.get<WebSocketManager>(), koin.get<WebSocketManager>())
        assertSame(koin.get<NotificationService>(), koin.get<NotificationService>())
        assertSame(sqsClient, koin.get<SqsClient>())

        sqsClient.close()
        dynamoDbClient.close()
        sesClient.close()
    }

    @Test
    fun `configureDependencyInjection leaves the endpoint at the AWS default when unset`() = testApplication {
        val registry = PrometheusMeterRegistry(PrometheusConfig.DEFAULT)
        val awsConfig = config.copy(awsEndpointUrl = null)
        lateinit var koin: Koin
        application {
            configureDependencyInjection(awsConfig, registry)
            koin = getKoin()
            routing { get("/ok") { call.respondText("ok") } }
        }

        assertEquals(HttpStatusCode.OK, client.get("/ok").status)

        val sqsClient = koin.get<SqsClient>()
        val dynamoDbClient = koin.get<DynamoDbClient>()
        val sesClient = koin.get<SesClient>()
        assertNull(sqsClient.config.endpointUrl)
        assertNull(dynamoDbClient.config.endpointUrl)
        assertNull(sesClient.config.endpointUrl)

        sqsClient.close()
        dynamoDbClient.close()
        sesClient.close()
    }

    @Test
    fun `module exposes the health endpoint over the fully wired application`() = testApplication {
        application { module(config) }

        val health = client.get("/health")

        assertEquals(HttpStatusCode.OK, health.status)
        assertTrue(health.bodyAsText().contains("notification-service"), health.bodyAsText())
        assertTrue(client.get("/metrics").bodyAsText().contains("jvm_memory_used_bytes"))
        assertEquals(
            HttpStatusCode.BadRequest,
            client.get("/api/v1/notifications").status,
        )
    }
}
