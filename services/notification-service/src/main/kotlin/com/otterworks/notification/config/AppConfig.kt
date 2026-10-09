package com.otterworks.notification.config

data class AppConfig(
    val port: Int,
    val awsRegion: String,
    val awsEndpointUrl: String?,
    val sqsQueueUrl: String,
    val snsTopicArn: String,
    val dynamoDbTableNotifications: String,
    val dynamoDbTablePreferences: String,
    val sesFromEmail: String,
    val sqsPollIntervalMs: Long,
    val sqsMaxMessages: Int,
    val sqsWaitTimeSeconds: Int,
    // Force the strict JSON parser normally gated behind the
    // chaos:notification-service:consumer_strict_schema Redis flag, so legacy
    // messages with epoch-int timestamps fail deserialization permanently.
    val strictSchema: Boolean = false,
    // Redirect the consumer at a nonexistent SQS queue so every poll fails
    // with a real AWS SQS error (QueueDoesNotExist / NonExistentQueue).
    val sqsAlwaysFail: Boolean = false,
    // Destination for consumer-failure alerts (admin-service ingest webhook).
    val adminServiceUrl: String = "http://admin-service:8089",
    val alertWebhookSecret: String? = null,
    // Clients only ever send "ping", so frames are capped well below the
    // container heap; larger frames close the socket with 1009 (TOO_BIG).
    val wsMaxFrameBytes: Long = DEFAULT_WS_MAX_FRAME_BYTES,
    val wsMaxConnectionsPerClient: Int = DEFAULT_WS_MAX_CONNECTIONS_PER_CLIENT,
    val wsMaxConnections: Int = DEFAULT_WS_MAX_CONNECTIONS,
) {
    // Queue URL the consumer actually polls. When the failure switch is on,
    // this points at a queue that does not exist in any account, so SQS
    // rejects every ReceiveMessage call without touching real resources.
    val effectiveSqsQueueUrl: String
        get() = when {
            !sqsAlwaysFail -> sqsQueueUrl
            sqsQueueUrl.isBlank() ->
                "https://sqs.$awsRegion.amazonaws.com/000000000000/otterworks-notifications-chaos-nonexistent"
            else -> "$sqsQueueUrl-chaos-nonexistent"
        }

    companion object {
        const val DEFAULT_WS_MAX_FRAME_BYTES: Long = 64L * 1024
        const val DEFAULT_WS_MAX_CONNECTIONS_PER_CLIENT: Int = 20
        const val DEFAULT_WS_MAX_CONNECTIONS: Int = 1000

        fun load(): AppConfig {
            return AppConfig(
                port = System.getenv("PORT")?.toIntOrNull() ?: 8086,
                awsRegion = System.getenv("AWS_REGION") ?: "us-east-1",
                awsEndpointUrl = System.getenv("AWS_ENDPOINT_URL"),
                sqsQueueUrl = System.getenv("SQS_QUEUE_URL")
                    ?: "http://localhost:4566/000000000000/otterworks-notifications",
                snsTopicArn = System.getenv("SNS_TOPIC_ARN")
                    ?: "arn:aws:sns:us-east-1:000000000000:otterworks-events",
                dynamoDbTableNotifications = System.getenv("DYNAMODB_TABLE_NOTIFICATIONS")
                    ?: "otterworks-notifications",
                dynamoDbTablePreferences = System.getenv("DYNAMODB_TABLE_PREFERENCES")
                    ?: "otterworks-notification-preferences",
                sesFromEmail = System.getenv("SES_FROM_EMAIL")
                    ?: "notifications@otterworks.io",
                sqsPollIntervalMs = System.getenv("SQS_POLL_INTERVAL_MS")?.toLongOrNull() ?: 5000L,
                sqsMaxMessages = System.getenv("SQS_MAX_MESSAGES")?.toIntOrNull() ?: 10,
                sqsWaitTimeSeconds = System.getenv("SQS_WAIT_TIME_SECONDS")?.toIntOrNull() ?: 20,
                strictSchema = System.getenv("NOTIFICATION_STRICT_SCHEMA")?.toBoolean() ?: false,
                sqsAlwaysFail = System.getenv("NOTIFICATION_SQS_ALWAYS_FAIL")?.toBoolean() ?: false,
                adminServiceUrl = System.getenv("ADMIN_SERVICE_URL") ?: "http://admin-service:8089",
                alertWebhookSecret = System.getenv("ALERT_WEBHOOK_SECRET")?.takeIf { it.isNotBlank() },
                wsMaxFrameBytes = System.getenv("WS_MAX_FRAME_BYTES")?.toLongOrNull()
                    ?.takeIf { it > 0 } ?: DEFAULT_WS_MAX_FRAME_BYTES,
                wsMaxConnectionsPerClient = System.getenv("WS_MAX_CONNECTIONS_PER_CLIENT")?.toIntOrNull()
                    ?.takeIf { it > 0 } ?: DEFAULT_WS_MAX_CONNECTIONS_PER_CLIENT,
                wsMaxConnections = System.getenv("WS_MAX_CONNECTIONS")?.toIntOrNull()
                    ?.takeIf { it > 0 } ?: DEFAULT_WS_MAX_CONNECTIONS,
            )
        }
    }
}
