package com.otterworks.notification.service

import aws.sdk.kotlin.services.ses.SesClient
import aws.sdk.kotlin.services.ses.model.SendEmailRequest
import aws.sdk.kotlin.services.ses.model.SendEmailResponse
import com.otterworks.notification.config.AppConfig
import io.mockk.coEvery
import io.mockk.coVerify
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
        sesFromEmail = "notifications@otterworks.io",
        sqsPollIntervalMs = 1000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )

    private val emailSender = EmailSender(sesClient, config)

    @Test
    fun `sendEmail builds a UTF-8 HTML message from the configured sender`() = runTest {
        val request = slot<SendEmailRequest>()
        coEvery { sesClient.sendEmail(capture(request)) } returns SendEmailResponse { messageId = "ses-1" }

        val sent = emailSender.sendEmail(
            toAddress = "user-1@otterworks.io",
            subject = "OtterWorks: A file has been shared with you",
            htmlBody = "<html><body><h2>File Shared</h2></body></html>",
        )

        assertTrue(sent)
        val captured = request.captured
        assertEquals("notifications@otterworks.io", captured.source)
        assertEquals(listOf("user-1@otterworks.io"), captured.destination?.toAddresses)
        assertEquals("OtterWorks: A file has been shared with you", captured.message?.subject?.data)
        assertEquals("UTF-8", captured.message?.subject?.charset)
        assertEquals("<html><body><h2>File Shared</h2></body></html>", captured.message?.body?.html?.data)
        assertEquals("UTF-8", captured.message?.body?.html?.charset)
    }

    @Test
    fun `sendEmail reports failure when SES rejects the message`() = runTest {
        coEvery { sesClient.sendEmail(any()) } throws RuntimeException("Email address is not verified")

        assertFalse(emailSender.sendEmail("user-1@otterworks.io", "subject", "<html/>"))

        coVerify(exactly = 1) { sesClient.sendEmail(any()) }
    }
}
