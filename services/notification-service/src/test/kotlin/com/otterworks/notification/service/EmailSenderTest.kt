package com.otterworks.notification.service

import aws.sdk.kotlin.services.ses.SesClient
import aws.sdk.kotlin.services.ses.model.SendEmailRequest
import aws.sdk.kotlin.services.ses.model.SendEmailResponse
import com.otterworks.notification.testConfig
import io.mockk.coEvery
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class EmailSenderTest {

    private val sesClient = mockk<SesClient>()
    private val sender = EmailSender(sesClient, testConfig())

    @Test
    fun `sendEmail builds a UTF-8 HTML message from the configured sender`() = runTest {
        val request = slot<SendEmailRequest>()
        coEvery { sesClient.sendEmail(capture(request)) } returns SendEmailResponse { messageId = "msg-1" }

        val sent = sender.sendEmail(
            toAddress = "user-1@otterworks.io",
            subject = "OtterWorks: A file has been shared with you",
            htmlBody = "<html><body><h2>File Shared</h2></body></html>",
        )

        assertTrue(sent)
        val captured = request.captured
        assertEquals("test@otterworks.io", captured.source)
        assertEquals(listOf("user-1@otterworks.io"), captured.destination?.toAddresses)
        val message = assertNotNull(captured.message)
        assertEquals("OtterWorks: A file has been shared with you", message.subject?.data)
        assertEquals("UTF-8", message.subject?.charset)
        assertEquals("<html><body><h2>File Shared</h2></body></html>", message.body?.html?.data)
        assertEquals("UTF-8", message.body?.html?.charset)
    }

    @Test
    fun `sendEmail reports failure instead of propagating an SES error`() = runTest {
        coEvery { sesClient.sendEmail(any()) } throws IllegalStateException("SES unavailable")

        assertFalse(sender.sendEmail("user-1@otterworks.io", "subject", "<html/>"))
    }
}
