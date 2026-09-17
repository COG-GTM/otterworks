package com.otterworks.notification.config

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class AppConfigTest {

    /**
     * The values below mirror the environment-variable contract of [AppConfig.load]: a variable
     * wins when it is set, otherwise the documented default applies. The tests run with none of
     * these variables set, so in practice the defaults are asserted.
     */
    private fun env(name: String) = System.getenv(name)

    @Test
    fun `load reads the port and AWS endpoint from the environment`() {
        val config = AppConfig.load()

        assertEquals(env("PORT")?.toIntOrNull() ?: 8086, config.port)
        assertEquals(env("AWS_REGION") ?: "us-east-1", config.awsRegion)
        assertEquals(env("AWS_ENDPOINT_URL"), config.awsEndpointUrl)
        assertTrue(config.port in 1..65535)
    }

    @Test
    fun `load defaults the messaging and storage targets to the local stack`() {
        val config = AppConfig.load()

        assertEquals(
            env("SQS_QUEUE_URL") ?: "http://localhost:4566/000000000000/otterworks-notifications",
            config.sqsQueueUrl,
        )
        assertEquals(
            env("SNS_TOPIC_ARN") ?: "arn:aws:sns:us-east-1:000000000000:otterworks-events",
            config.snsTopicArn,
        )
        assertEquals(
            env("DYNAMODB_TABLE_NOTIFICATIONS") ?: "otterworks-notifications",
            config.dynamoDbTableNotifications,
        )
        assertEquals(
            env("DYNAMODB_TABLE_PREFERENCES") ?: "otterworks-notification-preferences",
            config.dynamoDbTablePreferences,
        )
        assertEquals(env("SES_FROM_EMAIL") ?: "notifications@otterworks.io", config.sesFromEmail)
    }

    @Test
    fun `load defaults the SQS polling knobs`() {
        val config = AppConfig.load()

        assertEquals(env("SQS_POLL_INTERVAL_MS")?.toLongOrNull() ?: 5000L, config.sqsPollIntervalMs)
        assertEquals(env("SQS_MAX_MESSAGES")?.toIntOrNull() ?: 10, config.sqsMaxMessages)
        assertEquals(env("SQS_WAIT_TIME_SECONDS")?.toIntOrNull() ?: 20, config.sqsWaitTimeSeconds)
        assertTrue(config.sqsMaxMessages in 1..10)
        assertTrue(config.sqsWaitTimeSeconds in 0..20)
    }

    @Test
    fun `load produces a value-equal config on every call`() {
        val first = AppConfig.load()
        val second = AppConfig.load()

        assertEquals(first, second)
        assertEquals(first.hashCode(), second.hashCode())
        assertTrue(first.toString().contains("port=${first.port}"))
        assertEquals(9090, first.copy(port = 9090).port)
    }
}
