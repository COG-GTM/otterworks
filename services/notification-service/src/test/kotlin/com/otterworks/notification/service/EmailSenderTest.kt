package com.otterworks.notification.service

import aws.sdk.kotlin.services.ses.SesClient
import aws.sdk.kotlin.services.ses.model.Content
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
        sqsQueueUrl = "q",
        snsTopicArn = "t",
        dynamoDbTableNotifications = "n",
        dynamoDbTablePreferences = "p",
        sesFromEmail = "noreply@otterworks.io",
        sqsPollIntervalMs = 1000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )
    private val sender = EmailSender(sesClient, config)

    @Test
    fun `sends an html email from the configured sender`() = runTest {
        val request = slot<SendEmailRequest>()
        coEvery { sesClient.sendEmail(capture(request)) } returns SendEmailResponse { messageId = "msg-1" }

        assertTrue(sender.sendEmail("user@otterworks.io", "Hello", "<p>Hi</p>"))

        val sent = request.captured
        assertEquals("noreply@otterworks.io", sent.source)
        assertEquals(listOf("user@otterworks.io"), sent.destination?.toAddresses)
        assertEquals(Content { data = "Hello"; charset = "UTF-8" }, sent.message?.subject)
        assertEquals(Content { data = "<p>Hi</p>"; charset = "UTF-8" }, sent.message?.body?.html)
    }

    @Test
    fun `returns false instead of throwing when SES fails`() = runTest {
        coEvery { sesClient.sendEmail(any<SendEmailRequest>()) } throws RuntimeException("MessageRejected")

        assertFalse(sender.sendEmail("user@otterworks.io", "Hello", "<p>Hi</p>"))
    }
}
