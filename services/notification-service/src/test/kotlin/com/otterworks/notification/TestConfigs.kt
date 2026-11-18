package com.otterworks.notification

import com.otterworks.notification.config.AppConfig

fun testConfig(
    sqsAlwaysFail: Boolean = false,
    adminServiceUrl: String = "",
    awsEndpointUrl: String? = null,
    sqsPollIntervalMs: Long = 1000,
) = AppConfig(
    port = 8086,
    awsRegion = "us-east-1",
    awsEndpointUrl = awsEndpointUrl,
    sqsQueueUrl = "http://localhost:4566/000000000000/test-queue",
    snsTopicArn = "arn:aws:sns:us-east-1:000000000000:test-topic",
    dynamoDbTableNotifications = "test-notifications",
    dynamoDbTablePreferences = "test-preferences",
    sesFromEmail = "test@otterworks.io",
    sqsPollIntervalMs = sqsPollIntervalMs,
    sqsMaxMessages = 10,
    sqsWaitTimeSeconds = 5,
    sqsAlwaysFail = sqsAlwaysFail,
    adminServiceUrl = adminServiceUrl,
)
