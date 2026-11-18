package com.otterworks.notification.config

import com.otterworks.notification.testConfig
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class AppConfigTest {

    @Test
    fun `effective queue url is the configured url when failure switch is off`() {
        val config = testConfig()
        assertEquals(config.sqsQueueUrl, config.effectiveSqsQueueUrl)
    }

    @Test
    fun `effective queue url uses region-scoped nonexistent queue when url is blank`() {
        val config = testConfig(sqsAlwaysFail = true).copy(sqsQueueUrl = " ", awsRegion = "eu-west-1")
        assertEquals(
            "https://sqs.eu-west-1.amazonaws.com/000000000000/otterworks-notifications-chaos-nonexistent",
            config.effectiveSqsQueueUrl,
        )
    }

    @Test
    fun `load falls back to defaults for unset environment`() {
        val env = System.getenv()
        val config = AppConfig.load()
        if (env["PORT"] == null) assertEquals(8086, config.port)
        if (env["AWS_REGION"] == null) assertEquals("us-east-1", config.awsRegion)
        if (env["SQS_QUEUE_URL"] == null) {
            assertEquals("http://localhost:4566/000000000000/otterworks-notifications", config.sqsQueueUrl)
        }
        if (env["SNS_TOPIC_ARN"] == null) {
            assertEquals("arn:aws:sns:us-east-1:000000000000:otterworks-events", config.snsTopicArn)
        }
        if (env["DYNAMODB_TABLE_NOTIFICATIONS"] == null) {
            assertEquals("otterworks-notifications", config.dynamoDbTableNotifications)
        }
        if (env["DYNAMODB_TABLE_PREFERENCES"] == null) {
            assertEquals("otterworks-notification-preferences", config.dynamoDbTablePreferences)
        }
        if (env["SES_FROM_EMAIL"] == null) assertEquals("notifications@otterworks.io", config.sesFromEmail)
        if (env["SQS_POLL_INTERVAL_MS"] == null) assertEquals(5000L, config.sqsPollIntervalMs)
        if (env["SQS_MAX_MESSAGES"] == null) assertEquals(10, config.sqsMaxMessages)
        if (env["SQS_WAIT_TIME_SECONDS"] == null) assertEquals(20, config.sqsWaitTimeSeconds)
        if (env["NOTIFICATION_STRICT_SCHEMA"] == null) assertEquals(false, config.strictSchema)
        if (env["NOTIFICATION_SQS_ALWAYS_FAIL"] == null) assertEquals(false, config.sqsAlwaysFail)
        if (env["ADMIN_SERVICE_URL"] == null) assertEquals("http://admin-service:8089", config.adminServiceUrl)
        if (env["ALERT_WEBHOOK_SECRET"].isNullOrBlank()) assertNull(config.alertWebhookSecret)
        assertTrue(config.port > 0)
    }

    @Test
    fun `constructor defaults keep failure switches off`() {
        val config = AppConfig(
            port = 1, awsRegion = "r", awsEndpointUrl = null, sqsQueueUrl = "q", snsTopicArn = "t",
            dynamoDbTableNotifications = "n", dynamoDbTablePreferences = "p", sesFromEmail = "e",
            sqsPollIntervalMs = 1, sqsMaxMessages = 1, sqsWaitTimeSeconds = 1,
        )
        assertEquals(false, config.strictSchema)
        assertEquals(false, config.sqsAlwaysFail)
        assertEquals("http://admin-service:8089", config.adminServiceUrl)
        assertNull(config.alertWebhookSecret)
    }
}
