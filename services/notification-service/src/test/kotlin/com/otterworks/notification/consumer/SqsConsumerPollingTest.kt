package com.otterworks.notification.consumer

import aws.sdk.kotlin.services.sqs.SqsClient
import aws.sdk.kotlin.services.sqs.model.DeleteMessageRequest
import aws.sdk.kotlin.services.sqs.model.DeleteMessageResponse
import aws.sdk.kotlin.services.sqs.model.Message
import aws.sdk.kotlin.services.sqs.model.ReceiveMessageRequest
import aws.sdk.kotlin.services.sqs.model.ReceiveMessageResponse
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.model.SqsNotificationMessage
import com.otterworks.notification.service.NotificationService
import io.micrometer.prometheus.PrometheusConfig
import io.micrometer.prometheus.PrometheusMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals


class SqsConsumerPollingTest {

    private val sqsClient = mockk<SqsClient>()
    private val notificationService = mockk<NotificationService>(relaxed = true)
    private val meterRegistry = PrometheusMeterRegistry(PrometheusConfig.DEFAULT)
    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "http://localhost:4566/000000000000/test-queue",
        snsTopicArn = "arn:aws:sns:us-east-1:000000000000:test-topic",
        dynamoDbTableNotifications = "test-notifications",
        dynamoDbTablePreferences = "test-preferences",
        sesFromEmail = "test@otterworks.io",
        sqsPollIntervalMs = 20,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )

    private val consumer = SqsConsumer(sqsClient, notificationService, config, meterRegistry)

    private val validBody = """
        {
            "eventType": "file_shared",
            "fileId": "file-123",
            "ownerId": "owner-1",
            "sharedWithUserId": "user-2",
            "timestamp": "2024-01-01T00:00:00Z"
        }
    """.trimIndent()

    private fun message(body: String?, id: String = "m-1") = Message {
        this.body = body
        messageId = id
        receiptHandle = "receipt-$id"
    }

    private fun pollOnce(block: suspend () -> Unit) = runBlocking {
        val job = launch(Dispatchers.Default) { consumer.startPolling() }
        try {
            block()
        } finally {
            job.cancelAndJoin()
        }
    }

    @Test
    fun `polling processes a message and deletes it from the queue`() {
        val receive = slot<ReceiveMessageRequest>()
        coEvery { sqsClient.receiveMessage(capture(receive)) } returns
            ReceiveMessageResponse { messages = listOf(message(validBody)) } andThen
            ReceiveMessageResponse { messages = emptyList() }
        val delete = slot<DeleteMessageRequest>()
        coEvery { sqsClient.deleteMessage(capture(delete)) } returns DeleteMessageResponse {}

        pollOnce {
            coVerify(timeout = 10_000) { sqsClient.deleteMessage(any<DeleteMessageRequest>()) }
        }

        val processed = slot<SqsNotificationMessage>()
        coVerify { notificationService.processEvent(capture(processed)) }
        assertEquals("file_shared", processed.captured.eventType)
        assertEquals("user-2", processed.captured.sharedWithUserId)
        assertEquals("receipt-m-1", delete.captured.receiptHandle)
        assertEquals(config.sqsQueueUrl, receive.captured.queueUrl)
        assertEquals(config.sqsMaxMessages, receive.captured.maxNumberOfMessages)
        assertEquals(config.sqsWaitTimeSeconds, receive.captured.waitTimeSeconds)
    }

    @Test
    fun `an unparseable message is counted as an error and left on the queue`() {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } returns
            ReceiveMessageResponse { messages = listOf(message("not json at all")) } andThen
            ReceiveMessageResponse { messages = emptyList() }
        coEvery { sqsClient.deleteMessage(any<DeleteMessageRequest>()) } returns DeleteMessageResponse {}

        pollOnce {
            coVerify(timeout = 10_000, atLeast = 2) { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) }
        }

        coVerify(exactly = 0) { sqsClient.deleteMessage(any<DeleteMessageRequest>()) }
        coVerify(exactly = 0) { notificationService.processEvent(any()) }
        assertEquals(1.0, meterRegistry.counter("notifications.processing.errors").count())
    }

    @Test
    fun `a message without a body is skipped`() {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } returns
            ReceiveMessageResponse { messages = listOf(message(null)) } andThen
            ReceiveMessageResponse { messages = emptyList() }
        coEvery { sqsClient.deleteMessage(any<DeleteMessageRequest>()) } returns DeleteMessageResponse {}

        pollOnce {
            coVerify(timeout = 10_000, atLeast = 2) { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) }
        }

        coVerify(exactly = 0) { notificationService.processEvent(any()) }
        coVerify(exactly = 0) { sqsClient.deleteMessage(any<DeleteMessageRequest>()) }
    }

    @Test
    fun `a failure while processing does not stop the consumer`() {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } returns
            ReceiveMessageResponse { messages = listOf(message(validBody)) } andThen
            ReceiveMessageResponse { messages = emptyList() }
        coEvery { notificationService.processEvent(any()) } throws RuntimeException("dynamo down")

        pollOnce {
            coVerify(timeout = 10_000, atLeast = 3) { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) }
        }

        coVerify(exactly = 0) { sqsClient.deleteMessage(any<DeleteMessageRequest>()) }
    }

    @Test
    fun `a receive failure is retried after the backoff instead of killing the loop`() {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } throws RuntimeException("sqs unavailable")

        pollOnce {
            coVerify(timeout = 10_000, atLeast = 2) { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) }
        }

        coVerify(exactly = 0) { notificationService.processEvent(any()) }
        coVerify(exactly = 0) { sqsClient.deleteMessage(any<DeleteMessageRequest>()) }
    }
}
