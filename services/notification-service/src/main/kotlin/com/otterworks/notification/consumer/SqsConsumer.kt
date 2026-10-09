package com.otterworks.notification.consumer

import aws.sdk.kotlin.services.sqs.SqsClient
import aws.sdk.kotlin.services.sqs.model.DeleteMessageRequest
import aws.sdk.kotlin.services.sqs.model.ReceiveMessageRequest
import com.otterworks.notification.alerts.AlertPublisher
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.model.SqsNotificationMessage
import com.otterworks.notification.service.NotificationService
import io.micrometer.core.instrument.Counter
import io.micrometer.core.instrument.MeterRegistry
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import mu.KotlinLogging
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig

private val logger = KotlinLogging.logger {}

internal data class RedisSettings(
    val host: String,
    val port: Int,
    val password: String?,
    val ssl: Boolean,
)

// REDIS_PASSWORD (AUTH token) and REDIS_TLS are set for the shared ElastiCache,
// which rejects unauthenticated and plaintext connections.
internal fun redisSettingsFrom(env: (String) -> String?): RedisSettings = RedisSettings(
    host = env("REDIS_HOST") ?: "localhost",
    port = env("REDIS_PORT")?.toIntOrNull() ?: 6379,
    password = env("REDIS_PASSWORD")?.takeIf { it.isNotEmpty() },
    ssl = env("REDIS_TLS")?.trim()?.lowercase() in setOf("1", "true", "yes"),
)

// Lazy Redis pool for chaos flag checks.
private val redisPool: JedisPool by lazy {
    val settings = redisSettingsFrom(System::getenv)
    JedisPool(JedisPoolConfig(), settings.host, settings.port, 1000, settings.password, settings.ssl)
}

private fun chaosActive(flag: String): Boolean {
    return try {
        redisPool.resource.use { jedis -> jedis.exists(flag) }
    } catch (e: Exception) {
        false
    }
}

class SqsConsumer(
    private val sqsClient: SqsClient,
    private val notificationService: NotificationService,
    private val config: AppConfig,
    meterRegistry: MeterRegistry? = null,
    private val alertPublisher: AlertPublisher? = null,
) {
    private val processingErrorsCounter: Counter? =
        meterRegistry?.counter("notifications.processing.errors")
    // Standard lenient parser used in normal operation.
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    // CHAOS: strict parser that rejects messages whose timestamp field is not
    // a valid RFC 3339 string.  Legacy events emitted by older service versions
    // use Unix epoch integers for timestamps, which are rejected here.
    // When the chaos flag is active, every such message throws
    // SerializationException, is never deleted from the queue, and becomes
    // visible again after the SQS visibility timeout — causing queue depth to
    // climb indefinitely while the consumer appears healthy.
    private val strictJson = Json {
        ignoreUnknownKeys = false
        isLenient = false
    }

    suspend fun startPolling() = coroutineScope {
        logger.info { "Starting SQS consumer polling: ${config.effectiveSqsQueueUrl}" }
        if (config.sqsAlwaysFail) {
            logger.warn { "NOTIFICATION_SQS_ALWAYS_FAIL is enabled: polling a nonexistent SQS queue" }
        }

        while (isActive) {
            try {
                val request = ReceiveMessageRequest {
                    queueUrl = config.effectiveSqsQueueUrl
                    maxNumberOfMessages = config.sqsMaxMessages
                    waitTimeSeconds = config.sqsWaitTimeSeconds
                }

                val response = sqsClient.receiveMessage(request)
                val messages = response.messages ?: emptyList()

                if (messages.isNotEmpty()) {
                    logger.info { "Received ${messages.size} messages from SQS" }
                }

                for (msg in messages) {
                    launch {
                        try {
                            val body = msg.body ?: return@launch
                            val event = parseMessage(body)

                            if (event != null) {
                                notificationService.processEvent(event)

                                val deleteRequest = DeleteMessageRequest {
                                    queueUrl = config.effectiveSqsQueueUrl
                                    receiptHandle = msg.receiptHandle
                                }
                                sqsClient.deleteMessage(deleteRequest)
                                logger.debug { "Deleted SQS message: ${msg.messageId}" }
                            } else {
                                processingErrorsCounter?.increment()
                                logger.warn { "Failed to parse SQS message: ${msg.messageId}" }
                                alertPublisher?.notifyConsumerFailure(
                                    "Message ${msg.messageId} failed deserialization and was left in the queue"
                                )
                            }
                        } catch (e: Exception) {
                            logger.error(e) { "Error processing SQS message: ${msg.messageId}" }
                        }
                    }
                }

                if (messages.isEmpty()) {
                    delay(config.sqsPollIntervalMs)
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                logger.error(e) { "Error polling SQS" }
                if (config.sqsAlwaysFail) {
                    processingErrorsCounter?.increment()
                    try {
                        alertPublisher?.notifyConsumerFailure(
                            "ReceiveMessage failed for ${config.effectiveSqsQueueUrl}: ${e.message}"
                        )
                    } catch (alertError: Exception) {
                        logger.warn(alertError) { "Failed to publish consumer-failure alert" }
                    }
                }
                delay(config.sqsPollIntervalMs * 2)
            }
        }
    }

    internal fun parseMessage(body: String): SqsNotificationMessage? {
        val parser = if (config.strictSchema || chaosActive("chaos:notification-service:consumer_strict_schema")) strictJson else json
        return try {
            // Try parsing as direct message first
            parser.decodeFromString<SqsNotificationMessage>(body)
        } catch (_: Exception) {
            try {
                // Try unwrapping SNS envelope
                val snsWrapper = parser.decodeFromString<SnsEnvelope>(body)
                parser.decodeFromString<SqsNotificationMessage>(snsWrapper.Message)
            } catch (e: Exception) {
                logger.error(e) { "Failed to parse message body" }
                null
            }
        }
    }
}

@kotlinx.serialization.Serializable
internal data class SnsEnvelope(
    val Message: String,
    val MessageId: String = "",
    val TopicArn: String = "",
    val Type: String = "",
)
