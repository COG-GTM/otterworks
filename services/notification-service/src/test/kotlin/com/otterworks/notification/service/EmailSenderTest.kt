package com.otterworks.notification.service

import aws.sdk.kotlin.services.ses.SesClient
import aws.sdk.kotlin.services.ses.model.SendEmailRequest
import aws.sdk.kotlin.services.ses.model.SendEmailResponse
import com.otterworks.notification.config.AppConfig
import io.mockk.coEvery
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class EmailSenderTest {

    private val sesClient = mockk<SesClient>()
    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "http://localhost:4566/000000000000/test-queue",
        snsTopicArn = "arn:aws:sns:us-east-1:000000000000:test-topic",
        dynamoDbTableNotifications = "test-notifications",
        dynamoDbTablePreferences = "test-preferences",
        sesFromEmail = "no-reply@otterworks.io",
        sqsPollIntervalMs = 1000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )

    private val sender = EmailSender(sesClient, config)

    @Test
    fun `sendEmail builds an SES request from the configured sender and returns true`() = runTest {
        val request = slot<SendEmailRequest>()
        coEvery { sesClient.sendEmail(capture(request)) } returns SendEmailResponse { messageId = "ses-1" }

        val sent = sender.sendEmail("user-1@otterworks.io", "Subject line", "<html><body>hi</body></html>")

        assertTrue(sent)
        assertEquals("no-reply@otterworks.io", request.captured.source)
        assertEquals(listOf("user-1@otterworks.io"), request.captured.destination?.toAddresses)
        assertEquals("Subject line", request.captured.message?.subject?.data)
        assertEquals("UTF-8", request.captured.message?.subject?.charset)
        assertEquals("<html><body>hi</body></html>", request.captured.message?.body?.html?.data)
        assertEquals("UTF-8", request.captured.message?.body?.html?.charset)
    }

    @Test
    fun `sendEmail returns false when SES rejects the message`() = runTest {
        coEvery { sesClient.sendEmail(any<SendEmailRequest>()) } throws RuntimeException("throttled")

        assertFalse(sender.sendEmail("user-1@otterworks.io", "Subject", "<html/>"))
    }
}
