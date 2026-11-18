package com.otterworks.notification.consumer

import aws.sdk.kotlin.services.sqs.SqsClient
import aws.sdk.kotlin.services.sqs.model.DeleteMessageRequest
import aws.sdk.kotlin.services.sqs.model.DeleteMessageResponse
import aws.sdk.kotlin.services.sqs.model.Message
import aws.sdk.kotlin.services.sqs.model.QueueDoesNotExist
import aws.sdk.kotlin.services.sqs.model.ReceiveMessageRequest
import aws.sdk.kotlin.services.sqs.model.ReceiveMessageResponse
import com.otterworks.notification.alerts.AlertPublisher
import com.otterworks.notification.service.NotificationService
import com.otterworks.notification.testConfig
import io.micrometer.core.instrument.simple.SimpleMeterRegistry
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals

@OptIn(ExperimentalCoroutinesApi::class)
class SqsConsumerPollingTest {

    private val sqsClient = mockk<SqsClient>()
    private val notificationService = mockk<NotificationService>(relaxed = true)
    private val alertPublisher = mockk<AlertPublisher>(relaxed = true)
    private val registry = SimpleMeterRegistry()

    private val validBody = """{"eventType":"file_shared","fileId":"f1","sharedWithUserId":"u2","timestamp":"2024-01-01T00:00:00Z"}"""
    private val empty = ReceiveMessageResponse {}

    private fun consumer(alwaysFail: Boolean = false) =
        SqsConsumer(sqsClient, notificationService, testConfig(sqsAlwaysFail = alwaysFail), registry, alertPublisher)

    private fun TestScope.runPolling(consumer: SqsConsumer, millis: Long) {
        val job = launch { consumer.startPolling() }
        runCurrent()
        advanceTimeBy(millis)
        runCurrent()
        job.cancel()
    }

    private fun errors() = registry.counter("notifications.processing.errors").count()

    @Test
    fun `processes valid messages and deletes them`() = runTest {
        val receives = mutableListOf<ReceiveMessageRequest>()
        val deletes = mutableListOf<DeleteMessageRequest>()
        coEvery { sqsClient.receiveMessage(capture(receives)) } returnsMany listOf(
            ReceiveMessageResponse { messages = listOf(Message { messageId = "m1"; body = validBody; receiptHandle = "rh1" }) },
            empty,
        )
        coEvery { sqsClient.deleteMessage(capture(deletes)) } returns DeleteMessageResponse {}

        runPolling(consumer(), 500)

        coVerify(exactly = 1) { notificationService.processEvent(match { it.fileId == "f1" && it.sharedWithUserId == "u2" }) }
        assertEquals("rh1", deletes.single().receiptHandle)
        assertEquals("http://localhost:4566/000000000000/test-queue", deletes.single().queueUrl)
        assertEquals(10, receives.first().maxNumberOfMessages)
        assertEquals(5, receives.first().waitTimeSeconds)
        assertEquals(0.0, errors())
    }

    @Test
    fun `unparseable messages are left in queue and alerted`() = runTest {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } returnsMany listOf(
            ReceiveMessageResponse {
                messages = listOf(
                    Message { messageId = "bad"; body = "not json"; receiptHandle = "rh" },
                    Message { messageId = "nobody"; receiptHandle = "rh2" },
                )
            },
            empty,
        )

        runPolling(consumer(), 500)

        coVerify(exactly = 0) { sqsClient.deleteMessage(any<DeleteMessageRequest>()) }
        coVerify(exactly = 0) { notificationService.processEvent(any()) }
        verify(exactly = 1) { alertPublisher.notifyConsumerFailure(match { it.contains("bad") }) }
        assertEquals(1.0, errors())
    }

    @Test
    fun `processing failure keeps message for redelivery`() = runTest {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } returnsMany listOf(
            ReceiveMessageResponse { messages = listOf(Message { messageId = "m1"; body = validBody; receiptHandle = "rh1" }) },
            empty,
        )
        coEvery { notificationService.processEvent(any()) } throws RuntimeException("dynamo down")

        runPolling(consumer(), 500)

        coVerify(exactly = 0) { sqsClient.deleteMessage(any<DeleteMessageRequest>()) }
    }

    @Test
    fun `empty receive waits poll interval before next receive`() = runTest {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } returns empty

        runPolling(consumer(), 2500)

        coVerify(exactly = 3) { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) }
    }

    @Test
    fun `receive errors back off without alerting when failure switch is off`() = runTest {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } throws RuntimeException("network")

        runPolling(consumer(), 2500)

        coVerify(exactly = 2) { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) }
        verify(exactly = 0) { alertPublisher.notifyConsumerFailure(any()) }
        assertEquals(0.0, errors())
    }

    @Test
    fun `receive errors alert when failure switch is on`() = runTest {
        val receives = mutableListOf<ReceiveMessageRequest>()
        coEvery { sqsClient.receiveMessage(capture(receives)) } throws QueueDoesNotExist { message = "no queue" }
        every { alertPublisher.notifyConsumerFailure(any()) } throws RuntimeException("alert down") andThen Unit

        runPolling(consumer(alwaysFail = true), 2500)

        assertEquals("http://localhost:4566/000000000000/test-queue-chaos-nonexistent", receives.first().queueUrl)
        verify(exactly = 2) { alertPublisher.notifyConsumerFailure(match { it.contains("ReceiveMessage failed") }) }
        assertEquals(2.0, errors())
    }

    @Test
    fun `works without meter registry or alert publisher`() = runTest {
        coEvery { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) } returnsMany listOf(
            ReceiveMessageResponse { messages = listOf(Message { messageId = "bad"; body = "nope" }) },
        ) andThenThrows RuntimeException("network")

        runPolling(SqsConsumer(sqsClient, notificationService, testConfig(sqsAlwaysFail = true)), 2500)

        coVerify(atLeast = 2) { sqsClient.receiveMessage(any<ReceiveMessageRequest>()) }
    }
}
