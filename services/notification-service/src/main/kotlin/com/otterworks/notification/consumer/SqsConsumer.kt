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

private val logger = KotlinLogging.logger {}

class SqsConsumer(
    private val sqsClient: SqsClient,
    private val notificationService: NotificationService,
    private val config: AppConfig,
    meterRegistry: MeterRegistry? = null,
    private val alertPublisher: AlertPublisher? = null,
) {
    private val processingErrorsCounter: Counter? =
        meterRegistry?.counter("notifications.processing.errors")
    // Tolerant parser: producers evolve independently, so unknown fields are
    // ignored and timestamps are normalized by FlexibleTimestampSerializer.
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
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
        return try {
            // Try parsing as direct message first
            json.decodeFromString<SqsNotificationMessage>(body)
        } catch (_: Exception) {
            try {
                // Try unwrapping SNS envelope
                val snsWrapper = json.decodeFromString<SnsEnvelope>(body)
                json.decodeFromString<SqsNotificationMessage>(snsWrapper.Message)
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
