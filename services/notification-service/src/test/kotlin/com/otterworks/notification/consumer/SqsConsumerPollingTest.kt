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
import io.micrometer.core.instrument.simple.SimpleMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Exercises the polling loop of [SqsConsumer]. The loop runs until its coroutine is
 * cancelled, so every test drives it under a short timeout against a mocked SQS client.
 */
class SqsConsumerPollingTest {

    private val sqsClient = mockk<SqsClient>(relaxed = true)
    private val notificationService = mockk<NotificationService>(relaxed = true)
    private val meterRegistry = SimpleMeterRegistry()
    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "http://localhost:4566/000000000000/test-queue",
        snsTopicArn = "arn:aws:sns:us-east-1:000000000000:test-topic",
        dynamoDbTableNotifications = "test-notifications",
        dynamoDbTablePreferences = "test-preferences",
        sesFromEmail = "notifications@otterworks.io",
        sqsPollIntervalMs = 5,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 1,
    )
    private val consumer = SqsConsumer(sqsClient, notificationService, config, meterRegistry)

    private val fileSharedBody = """
        {
            "eventType": "file_shared",
            "fileId": "file-123",
            "ownerId": "owner-1",
            "sharedWithUserId": "user-2",
            "timestamp": "2024-01-01T00:00:00Z"
        }
    """.trimIndent()

    private fun message(body: String?, id: String = "msg-1") = Message {
        this.body = body
        messageId = id
        receiptHandle = "receipt-$id"
    }

    /** One batch, then an empty queue, so the loop settles instead of spinning on the same batch. */
    private fun receiveOnce(vararg messages: Message) {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } returns
            ReceiveMessageResponse { this.messages = messages.toList() } andThen
            ReceiveMessageResponse { this.messages = emptyList() }
    }

    /**
     * Runs the polling loop until it is cancelled, which is the only way it terminates.
     * A multi-threaded dispatcher is required because the loop only yields to the coroutines
     * that handle each message once the queue comes back empty.
     */
    private fun poll(millis: Long = 300) = runBlocking(Dispatchers.Default) {
        assertNull(withTimeoutOrNull(millis) { consumer.startPolling() })
    }

    @Test
    fun `polling processes a message and deletes it from the queue`() {
        val receive = slot<ReceiveMessageRequest>()
        coEvery { sqsClient.receiveMessage(capture(receive)) } returns ReceiveMessageResponse {
            messages = listOf(message(fileSharedBody))
        } andThen ReceiveMessageResponse { messages = emptyList() }
        val delete = slot<DeleteMessageRequest>()
        coEvery { sqsClient.deleteMessage(capture(delete)) } returns DeleteMessageResponse {}

        poll()

        assertEquals(config.sqsQueueUrl, receive.captured.queueUrl)
        assertEquals(10, receive.captured.maxNumberOfMessages)
        assertEquals(1, receive.captured.waitTimeSeconds)
        assertEquals(config.sqsQueueUrl, delete.captured.queueUrl)
        assertEquals("receipt-msg-1", delete.captured.receiptHandle)
        coVerify(atLeast = 1) {
            notificationService.processEvent(
                match<SqsNotificationMessage> { it.eventType == "file_shared" && it.fileId == "file-123" }
            )
        }
    }

    @Test
    fun `polling counts unparseable messages and leaves them on the queue`() {
        receiveOnce(message("not json at all"))

        poll()

        assertTrue(meterRegistry.counter("notifications.processing.errors").count() >= 1.0)
        coVerify(exactly = 0) { sqsClient.deleteMessage(any<DeleteMessageRequest>()) }
        coVerify(exactly = 0) { notificationService.processEvent(any()) }
    }

    @Test
    fun `polling skips messages without a body`() {
        receiveOnce(message(null))

        poll()

        coVerify(exactly = 0) { sqsClient.deleteMessage(any<DeleteMessageRequest>()) }
        coVerify(exactly = 0) { notificationService.processEvent(any()) }
        assertEquals(0.0, meterRegistry.counter("notifications.processing.errors").count())
    }

    @Test
    fun `polling swallows failures raised while handling a message`() {
        receiveOnce(message(fileSharedBody))
        coEvery { notificationService.processEvent(any()) } throws IllegalStateException("dynamo down")

        poll()

        coVerify(atLeast = 1) { notificationService.processEvent(any()) }
        coVerify(exactly = 0) { sqsClient.deleteMessage(any<DeleteMessageRequest>()) }
    }

    @Test
    fun `polling waits between empty receives`() {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } returns ReceiveMessageResponse {
            messages = emptyList()
        }

        poll(100)

        coVerify(atLeast = 1) { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) }
        coVerify(exactly = 0) { notificationService.processEvent(any()) }
    }

    @Test
    fun `polling recovers from receive failures and keeps polling`() {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } throws
            IllegalStateException("sqs unavailable")

        poll(100)

        coVerify(atLeast = 2) { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) }
    }
}
