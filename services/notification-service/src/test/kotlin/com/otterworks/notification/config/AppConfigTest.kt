package com.otterworks.notification.config

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class AppConfigTest {

    /**
     * [AppConfig.load] reads process environment variables, which cannot be mutated from inside
     * the test JVM, so each assertion mirrors the "environment or default" contract instead of
     * assuming an empty environment.
     */
    @Test
    fun `load resolves every setting from the environment or its default`() {
        val config = AppConfig.load()

        assertEquals(System.getenv("PORT")?.toIntOrNull() ?: 8086, config.port)
        assertEquals(System.getenv("AWS_REGION") ?: "us-east-1", config.awsRegion)
        assertEquals(System.getenv("AWS_ENDPOINT_URL"), config.awsEndpointUrl)
        assertEquals(
            System.getenv("SQS_QUEUE_URL")
                ?: "http://localhost:4566/000000000000/otterworks-notifications",
            config.sqsQueueUrl,
        )
        assertEquals(
            System.getenv("SNS_TOPIC_ARN") ?: "arn:aws:sns:us-east-1:000000000000:otterworks-events",
            config.snsTopicArn,
        )
        assertEquals(
            System.getenv("DYNAMODB_TABLE_NOTIFICATIONS") ?: "otterworks-notifications",
            config.dynamoDbTableNotifications,
        )
        assertEquals(
            System.getenv("DYNAMODB_TABLE_PREFERENCES") ?: "otterworks-notification-preferences",
            config.dynamoDbTablePreferences,
        )
        assertEquals(System.getenv("SES_FROM_EMAIL") ?: "notifications@otterworks.io", config.sesFromEmail)
        assertEquals(System.getenv("SQS_POLL_INTERVAL_MS")?.toLongOrNull() ?: 5000L, config.sqsPollIntervalMs)
        assertEquals(System.getenv("SQS_MAX_MESSAGES")?.toIntOrNull() ?: 10, config.sqsMaxMessages)
        assertEquals(System.getenv("SQS_WAIT_TIME_SECONDS")?.toIntOrNull() ?: 20, config.sqsWaitTimeSeconds)
    }

    @Test
    fun `load is deterministic for a given environment`() {
        assertEquals(AppConfig.load(), AppConfig.load())
    }

    @Test
    fun `config is a value object`() {
        val config = AppConfig(
            port = 8086,
            awsRegion = "us-east-1",
            awsEndpointUrl = null,
            sqsQueueUrl = "queue",
            snsTopicArn = "topic",
            dynamoDbTableNotifications = "notifications",
            dynamoDbTablePreferences = "preferences",
            sesFromEmail = "notifications@otterworks.io",
            sqsPollIntervalMs = 5000,
            sqsMaxMessages = 10,
            sqsWaitTimeSeconds = 20,
        )

        assertEquals(config, config.copy())
        assertEquals(config.hashCode(), config.copy().hashCode())
        assertEquals(9090, config.copy(port = 9090).port)
        assertEquals(8086, config.component1())
        assertEquals("us-east-1", config.component2())
        assertTrue(config.toString().contains("otterworks.io"))
        assertFalse(config == config.copy(port = 1))
    }
}
