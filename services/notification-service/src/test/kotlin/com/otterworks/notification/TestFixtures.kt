package com.otterworks.notification

import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.model.Notification

/** Deterministic config used by every unit test; no live endpoints are ever contacted. */
fun testConfig(
    awsEndpointUrl: String? = null,
    sqsPollIntervalMs: Long = 1000,
): AppConfig = AppConfig(
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
)

fun notification(
    id: String = "n-1",
    userId: String = "user-1",
    read: Boolean = false,
    deliveredVia: List<String> = listOf("in_app"),
): Notification = Notification(
    id = id,
    userId = userId,
    type = "file_shared",
    title = "File Shared With You",
    message = "A file has been shared with you.",
    resourceId = "file-1",
    resourceType = "file",
    actorId = "actor-1",
    read = read,
    deliveredVia = deliveredVia,
    createdAt = "2024-01-01T00:00:00Z",
)
