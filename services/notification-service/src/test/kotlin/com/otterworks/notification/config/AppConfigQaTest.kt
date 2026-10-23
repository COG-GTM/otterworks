package com.otterworks.notification.config

import kotlin.test.Test
import kotlin.test.assertEquals

class AppConfigQaTest {
    private fun cfg(url: String, fail: Boolean) = AppConfig(
        port = 8086, awsRegion = "eu-west-1", awsEndpointUrl = null, sqsQueueUrl = url, snsTopicArn = "t",
        dynamoDbTableNotifications = "n", dynamoDbTablePreferences = "p", sesFromEmail = "f",
        sqsPollIntervalMs = 1, sqsMaxMessages = 1, sqsWaitTimeSeconds = 0, sqsAlwaysFail = fail,
    )

    @Test
    fun `effective queue is the configured queue when the failure switch is off`() {
        assertEquals("http://q/notif", cfg("http://q/notif", false).effectiveSqsQueueUrl)
    }

    @Test
    fun `blank queue with failure switch points at a regional nonexistent queue`() {
        assertEquals(
            "https://sqs.eu-west-1.amazonaws.com/000000000000/otterworks-notifications-chaos-nonexistent",
            cfg("", true).effectiveSqsQueueUrl,
        )
    }

    @Test
    fun `defaults load without environment overrides`() {
        val c = AppConfig.load()
        assertEquals("otterworks-notification-preferences", System.getenv("DYNAMODB_TABLE_PREFERENCES") ?: c.dynamoDbTablePreferences)
        assertEquals(c.sqsAlwaysFail, System.getenv("NOTIFICATION_SQS_ALWAYS_FAIL")?.toBoolean() ?: false)
    }
}
