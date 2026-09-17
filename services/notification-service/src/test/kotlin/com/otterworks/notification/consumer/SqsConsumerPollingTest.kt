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
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class SqsConsumerPollingTest {

    private val sqsClient = mockk<SqsClient>()
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
        sesFromEmail = "test@otterworks.io",
        sqsPollIntervalMs = 20,
        sqsMaxMessages = 7,
        sqsWaitTimeSeconds = 3,
    )

    private val consumer = SqsConsumer(sqsClient, notificationService, config, meterRegistry)

    private val fileSharedBody = """
        {"eventType":"file_shared","fileId":"file-1","ownerId":"owner-1",
         "sharedWithUserId":"user-2","timestamp":"2024-01-01T00:00:00Z"}
    """.trimIndent()

    private fun message(body: String?) = Message {
        this.body = body
        messageId = "m-1"
        receiptHandle = "rh-1"
    }

    private fun batch(vararg messages: Message) = ReceiveMessageResponse {
        this.messages = messages.toList()
    }

    private val emptyBatch = ReceiveMessageResponse { messages = emptyList() }

    private suspend fun awaitCounter(name: String, atLeast: Double) = withTimeout(10_000) {
        while (meterRegistry.counter(name).count() < atLeast) {
            delay(5)
        }
    }

    @Test
    fun `startPolling processes a message and deletes it from the queue`() = runBlocking {
        val deleted = CompletableDeferred<DeleteMessageRequest>()
        val received = mutableListOf<ReceiveMessageRequest>()
        coEvery { sqsClient.receiveMessage(capture(received)) } returns
            batch(message(fileSharedBody)) andThen emptyBatch
        coEvery { sqsClient.deleteMessage(any()) } coAnswers {
            deleted.complete(firstArg())
            DeleteMessageResponse { }
        }

        val job = launch(Dispatchers.Default) { consumer.startPolling() }
        val deleteRequest = withTimeout(10_000) { deleted.await() }
        job.cancelAndJoin()

        assertEquals("rh-1", deleteRequest.receiptHandle)
        assertEquals(config.sqsQueueUrl, deleteRequest.queueUrl)
        assertEquals(config.sqsQueueUrl, received.first().queueUrl)
        assertEquals(7, received.first().maxNumberOfMessages)
        assertEquals(3, received.first().waitTimeSeconds)
        coVerify(exactly = 1) {
            notificationService.processEvent(
                SqsNotificationMessage(
                    eventType = "file_shared",
                    fileId = "file-1",
                    ownerId = "owner-1",
                    sharedWithUserId = "user-2",
                    timestamp = "2024-01-01T00:00:00Z",
                )
            )
        }
    }

    @Test
    fun `startPolling counts unparseable messages and leaves them on the queue`() = runBlocking {
        coEvery { sqsClient.receiveMessage(any()) } returns batch(message("<not json>")) andThen emptyBatch
        coEvery { sqsClient.deleteMessage(any()) } returns DeleteMessageResponse { }

        val job = launch(Dispatchers.Default) { consumer.startPolling() }
        awaitCounter("notifications.processing.errors", 1.0)
        job.cancelAndJoin()

        coVerify(exactly = 0) { sqsClient.deleteMessage(any()) }
        coVerify(exactly = 0) { notificationService.processEvent(any()) }
    }

    @Test
    fun `startPolling skips messages without a body`() = runBlocking {
        val polled = CompletableDeferred<Unit>()
        var calls = 0
        coEvery { sqsClient.receiveMessage(any()) } coAnswers {
            calls++
            when (calls) {
                1 -> batch(message(null))
                else -> emptyBatch.also { if (!polled.isCompleted) polled.complete(Unit) }
            }
        }

        val job = launch(Dispatchers.Default) { consumer.startPolling() }
        withTimeout(10_000) { polled.await() }
        job.cancelAndJoin()

        coVerify(exactly = 0) { notificationService.processEvent(any()) }
        assertEquals(0.0, meterRegistry.counter("notifications.processing.errors").count())
    }

    @Test
    fun `startPolling keeps the message when processing throws`() = runBlocking {
        val attempted = CompletableDeferred<Unit>()
        coEvery { sqsClient.receiveMessage(any()) } returns batch(message(fileSharedBody)) andThen emptyBatch
        coEvery { notificationService.processEvent(any()) } coAnswers {
            attempted.complete(Unit)
            throw RuntimeException("DynamoDB unavailable")
        }

        val job = launch(Dispatchers.Default) { consumer.startPolling() }
        withTimeout(10_000) { attempted.await() }
        delay(50)
        job.cancelAndJoin()

        coVerify(exactly = 0) { sqsClient.deleteMessage(any()) }
    }

    @Test
    fun `startPolling tolerates a receive response without a message list`() = runBlocking {
        val polled = CompletableDeferred<Unit>()
        var calls = 0
        coEvery { sqsClient.receiveMessage(any()) } coAnswers {
            calls++
            if (calls >= 2 && !polled.isCompleted) polled.complete(Unit)
            ReceiveMessageResponse { messages = null }
        }

        val job = launch(Dispatchers.Default) { consumer.startPolling() }
        withTimeout(10_000) { polled.await() }
        job.cancelAndJoin()

        coVerify(exactly = 0) { notificationService.processEvent(any()) }
        coVerify(exactly = 0) { sqsClient.deleteMessage(any()) }
    }

    @Test
    fun `a consumer without a meter registry still survives an unparseable message`() = runBlocking {
        val unmeteredConsumer = SqsConsumer(sqsClient, notificationService, config)
        val polled = CompletableDeferred<Unit>()
        var calls = 0
        coEvery { sqsClient.receiveMessage(any()) } coAnswers {
            calls++
            if (calls >= 3 && !polled.isCompleted) polled.complete(Unit)
            batch(message("<not json>"))
        }

        val job = launch(Dispatchers.Default) { unmeteredConsumer.startPolling() }
        withTimeout(10_000) { polled.await() }
        job.cancelAndJoin()

        coVerify(exactly = 0) { sqsClient.deleteMessage(any()) }
        assertEquals(0.0, meterRegistry.counter("notifications.processing.errors").count())
    }

    @Test
    fun `the SNS envelope exposes the inner message and its metadata`() {
        val envelope = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
            .decodeFromString(
                SnsEnvelope.serializer(),
                """{"Type":"Notification","MessageId":"sns-1","TopicArn":"arn:topic","Message":"{}"}""",
            )

        assertEquals("Notification", envelope.Type)
        assertEquals("sns-1", envelope.MessageId)
        assertEquals("arn:topic", envelope.TopicArn)
        assertEquals("{}", envelope.Message)
        assertEquals(SnsEnvelope(Message = "{}"), envelope.copy(MessageId = "", TopicArn = "", Type = ""))
        assertEquals(SnsEnvelope(Message = "{}").hashCode(), SnsEnvelope(Message = "{}").hashCode())
        assertTrue(envelope.toString().contains("sns-1"), envelope.toString())
    }

    @Test
    fun `startPolling backs off and keeps polling after a receive failure`() = runBlocking {
        val recovered = CompletableDeferred<Unit>()
        var calls = 0
        coEvery { sqsClient.receiveMessage(any()) } coAnswers {
            calls++
            if (calls == 1) throw RuntimeException("SQS unavailable")
            emptyBatch.also { if (!recovered.isCompleted) recovered.complete(Unit) }
        }

        val job = launch(Dispatchers.Default) { consumer.startPolling() }
        withTimeout(10_000) { recovered.await() }
        job.cancelAndJoin()

        assertTrue(calls >= 2, "expected polling to resume after the backoff, calls=$calls")
        coVerify(exactly = 0) { notificationService.processEvent(any()) }
    }
}
