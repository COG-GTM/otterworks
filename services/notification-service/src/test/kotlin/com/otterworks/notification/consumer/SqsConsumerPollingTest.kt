package com.otterworks.notification.consumer

import aws.sdk.kotlin.services.sqs.SqsClient
import aws.sdk.kotlin.services.sqs.model.DeleteMessageRequest
import aws.sdk.kotlin.services.sqs.model.DeleteMessageResponse
import aws.sdk.kotlin.services.sqs.model.Message
import aws.sdk.kotlin.services.sqs.model.ReceiveMessageRequest
import aws.sdk.kotlin.services.sqs.model.ReceiveMessageResponse
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.testConfig
import io.micrometer.core.instrument.simple.SimpleMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
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

/**
 * Drives [SqsConsumer.startPolling] against a mocked SQS client. The loop runs on a real
 * dispatcher but every boundary is mocked, and each test cancels the polling job as soon as
 * the behaviour under test has been observed.
 */
class SqsConsumerPollingTest {

    private val sqsClient = mockk<SqsClient>()
    private val notificationService = mockk<NotificationService>(relaxed = true)
    private val meterRegistry = SimpleMeterRegistry()
    private val config = testConfig(sqsPollIntervalMs = 20)

    private val consumer = SqsConsumer(sqsClient, notificationService, config, meterRegistry)

    private val fileSharedBody = """
        {"eventType":"file_shared","fileId":"file-1","ownerId":"owner-1",
         "sharedWithUserId":"user-2","timestamp":"2024-01-01T00:00:00Z"}
    """.trimIndent()

    private fun message(body: String?, id: String = "m-1") = Message {
        this.body = body
        receiptHandle = "rh-$id"
        messageId = id
    }

    private fun idleResponse() = ReceiveMessageResponse { messages = emptyList() }

    /** Runs the polling loop until [signal] completes, then cancels it. */
    private fun <T> pollUntil(signal: CompletableDeferred<T>): T = runBlocking {
        val job = launch(Dispatchers.Default) { consumer.startPolling() }
        try {
            withTimeout(15_000) { signal.await() }
        } finally {
            job.cancelAndJoin()
        }
    }

    private fun errorCount(): Double =
        meterRegistry.find("notifications.processing.errors").counter()?.count() ?: 0.0

    @Test
    fun `a received message is processed and then deleted from the queue`() {
        val receiveRequest = slot<ReceiveMessageRequest>()
        coEvery { sqsClient.receiveMessage(capture(receiveRequest)) } returns
            ReceiveMessageResponse { messages = listOf(message(fileSharedBody)) } andThen idleResponse()
        val deleted = CompletableDeferred<DeleteMessageRequest>()
        coEvery { sqsClient.deleteMessage(any()) } coAnswers {
            deleted.complete(firstArg())
            DeleteMessageResponse {}
        }

        val deleteRequest = pollUntil(deleted)

        assertEquals(config.sqsQueueUrl, receiveRequest.captured.queueUrl)
        assertEquals(config.sqsMaxMessages, receiveRequest.captured.maxNumberOfMessages)
        assertEquals(config.sqsWaitTimeSeconds, receiveRequest.captured.waitTimeSeconds)
        assertEquals(config.sqsQueueUrl, deleteRequest.queueUrl)
        assertEquals("rh-m-1", deleteRequest.receiptHandle)
        coVerify {
            notificationService.processEvent(
                match { it.eventType == "file_shared" && it.sharedWithUserId == "user-2" },
            )
        }
        assertEquals(0.0, errorCount())
    }

    @Test
    fun `an unparseable message is counted as an error and left on the queue`() {
        coEvery { sqsClient.receiveMessage(any()) } returns
            ReceiveMessageResponse { messages = listOf(message("<<not json>>")) } andThen idleResponse()
        coEvery { sqsClient.deleteMessage(any()) } returns DeleteMessageResponse {}

        val counted = CompletableDeferred<Unit>()
        runBlocking {
            val job = launch(Dispatchers.Default) { consumer.startPolling() }
            launch {
                while (errorCount() < 1.0) delay(10)
                counted.complete(Unit)
            }
            try {
                withTimeout(15_000) { counted.await() }
            } finally {
                job.cancelAndJoin()
            }
        }

        assertEquals(1.0, errorCount())
        coVerify(exactly = 0) { notificationService.processEvent(any()) }
        coVerify(exactly = 0) { sqsClient.deleteMessage(any()) }
    }

    @Test
    fun `a message without a body is ignored`() {
        val polls = mutableListOf<ReceiveMessageRequest>()
        val secondPoll = CompletableDeferred<Unit>()
        coEvery { sqsClient.receiveMessage(any()) } coAnswers {
            polls.add(firstArg())
            if (polls.size == 1) {
                ReceiveMessageResponse { messages = listOf(message(body = null)) }
            } else {
                secondPoll.complete(Unit)
                idleResponse()
            }
        }

        pollUntil(secondPoll)

        coVerify(exactly = 0) { notificationService.processEvent(any()) }
        assertEquals(0.0, errorCount())
    }

    @Test
    fun `a failure while processing a message does not stop the consumer`() {
        val polls = mutableListOf<ReceiveMessageRequest>()
        val thirdPoll = CompletableDeferred<Unit>()
        coEvery { sqsClient.receiveMessage(any()) } coAnswers {
            polls.add(firstArg())
            when (polls.size) {
                1 -> ReceiveMessageResponse { messages = listOf(message(fileSharedBody)) }
                2 -> idleResponse()
                else -> {
                    thirdPoll.complete(Unit)
                    idleResponse()
                }
            }
        }
        coEvery { notificationService.processEvent(any()) } throws IllegalStateException("DynamoDB down")

        pollUntil(thirdPoll)

        assertTrue(polls.size >= 3, "the consumer should keep polling after a processing failure")
        coVerify(exactly = 0) { sqsClient.deleteMessage(any()) }
    }

    @Test
    fun `a failure while polling is retried after a back-off`() {
        val polls = mutableListOf<ReceiveMessageRequest>()
        val recovered = CompletableDeferred<Unit>()
        coEvery { sqsClient.receiveMessage(any()) } coAnswers {
            polls.add(firstArg())
            if (polls.size == 1) {
                throw IllegalStateException("SQS unreachable")
            }
            recovered.complete(Unit)
            idleResponse()
        }

        pollUntil(recovered)

        assertTrue(polls.size >= 2, "the consumer should retry after a polling failure")
    }
}
