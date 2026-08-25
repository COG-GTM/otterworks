package com.otterworks.notification.config

import kotlin.test.Test
import kotlin.test.assertEquals

class AppConfigTest {

    @Test
    fun `load falls back to documented defaults when no environment is set`() {
        val config = AppConfig.load()

        assertEquals(System.getenv("PORT")?.toIntOrNull() ?: 8086, config.port)
        assertEquals(System.getenv("AWS_REGION") ?: "us-east-1", config.awsRegion)
        assertEquals(System.getenv("AWS_ENDPOINT_URL"), config.awsEndpointUrl)
        assertEquals(
            System.getenv("SQS_QUEUE_URL") ?: "http://localhost:4566/000000000000/otterworks-notifications",
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
    fun `load is stable across invocations`() {
        assertEquals(AppConfig.load(), AppConfig.load())
    }

    @Test
    fun `copy overrides a single field and leaves the rest untouched`() {
        val base = AppConfig.load()

        val overridden = base.copy(port = 9999, awsEndpointUrl = "http://localstack:4566")

        assertEquals(9999, overridden.port)
        assertEquals("http://localstack:4566", overridden.awsEndpointUrl)
        assertEquals(base.awsRegion, overridden.awsRegion)
        assertEquals(base.sqsQueueUrl, overridden.sqsQueueUrl)
    }
}
