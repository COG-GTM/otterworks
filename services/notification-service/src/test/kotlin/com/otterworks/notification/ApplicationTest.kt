package com.otterworks.notification

import io.ktor.client.request.get
import io.ktor.http.HttpStatusCode
import io.ktor.server.testing.testApplication
import org.koin.core.context.GlobalContext
import org.koin.core.context.stopKoin
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

class ApplicationTest {

    @AfterTest
    fun tearDown() {
        stopKoin()
    }

    @Test
    fun `module wires dependencies and serves health`() = testApplication {
        application {
            module(testConfig(awsEndpointUrl = "http://127.0.0.1:1", sqsPollIntervalMs = 60_000))
        }
        assertEquals(HttpStatusCode.OK, client.get("/health").status)
        val koin = GlobalContext.get()
        assertNotNull(koin.get<com.otterworks.notification.service.NotificationService>())
        assertNotNull(koin.get<com.otterworks.notification.service.EmailSender>())
        assertNotNull(koin.get<com.otterworks.notification.alerts.AlertPublisher>())
        assertNotNull(koin.get<aws.sdk.kotlin.services.dynamodb.DynamoDbClient>())
        assertNotNull(koin.get<aws.sdk.kotlin.services.ses.SesClient>())
    }

    @Test
    fun `module wires AWS clients without endpoint override`() = testApplication {
        application {
            module(testConfig(awsEndpointUrl = null, sqsPollIntervalMs = 60_000))
        }
        assertEquals(HttpStatusCode.OK, client.get("/health").status)
        val koin = GlobalContext.get()
        assertNotNull(koin.get<aws.sdk.kotlin.services.dynamodb.DynamoDbClient>())
        assertNotNull(koin.get<aws.sdk.kotlin.services.ses.SesClient>())
        assertNotNull(koin.get<aws.sdk.kotlin.services.sqs.SqsClient>())
    }
}
