package com.otterworks.notification.config

import org.junit.Assume.assumeTrue
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class AppConfigTest {

    private val overridableVars = listOf(
        "PORT",
        "AWS_REGION",
        "AWS_ENDPOINT_URL",
        "SQS_QUEUE_URL",
        "SNS_TOPIC_ARN",
        "DYNAMODB_TABLE_NOTIFICATIONS",
        "DYNAMODB_TABLE_PREFERENCES",
        "SES_FROM_EMAIL",
        "SQS_POLL_INTERVAL_MS",
        "SQS_MAX_MESSAGES",
        "SQS_WAIT_TIME_SECONDS",
    )

    @Test
    fun `load falls back to the documented defaults when no env overrides are present`() {
        assumeTrue(overridableVars.all { System.getenv(it) == null })

        val config = AppConfig.load()

        assertEquals(8086, config.port)
        assertEquals("us-east-1", config.awsRegion)
        assertNull(config.awsEndpointUrl)
        assertEquals(
            "http://localhost:4566/000000000000/otterworks-notifications",
            config.sqsQueueUrl,
        )
        assertEquals("arn:aws:sns:us-east-1:000000000000:otterworks-events", config.snsTopicArn)
        assertEquals("otterworks-notifications", config.dynamoDbTableNotifications)
        assertEquals("otterworks-notification-preferences", config.dynamoDbTablePreferences)
        assertEquals("notifications@otterworks.io", config.sesFromEmail)
        assertEquals(5000L, config.sqsPollIntervalMs)
        assertEquals(10, config.sqsMaxMessages)
        assertEquals(20, config.sqsWaitTimeSeconds)
    }

    @Test
    fun `load reflects the process environment when overrides are present`() {
        val config = AppConfig.load()

        System.getenv("PORT")?.toIntOrNull()?.let { assertEquals(it, config.port) }
        System.getenv("AWS_REGION")?.let { assertEquals(it, config.awsRegion) }
        System.getenv("AWS_ENDPOINT_URL")?.let { assertEquals(it, config.awsEndpointUrl) }
        System.getenv("SQS_MAX_MESSAGES")?.toIntOrNull()?.let { assertEquals(it, config.sqsMaxMessages) }
    }

    @Test
    fun `config is a value type - copy and equality are structural`() {
        val a = AppConfig.load()
        val b = a.copy()
        val c = a.copy(port = a.port + 1)

        assertEquals(a, b)
        assertEquals(a.hashCode(), b.hashCode())
        assertEquals(false, a == c)
        assertEquals(a.port + 1, c.port)
        assertEquals(true, a.toString().contains("port="))
    }
}
