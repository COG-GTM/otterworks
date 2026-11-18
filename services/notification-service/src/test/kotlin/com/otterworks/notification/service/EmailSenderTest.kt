package com.otterworks.notification.service

import aws.sdk.kotlin.services.ses.SesClient
import aws.sdk.kotlin.services.ses.model.Content
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
import kotlin.test.assertTrue

class EmailSenderTest {

    private val ses = mockk<SesClient>()
    private val sender = EmailSender(ses, testConfig())

    @Test
    fun `sendEmail builds SES request and returns true`() = runTest {
        val captured = slot<SendEmailRequest>()
        coEvery { ses.sendEmail(capture(captured)) } returns SendEmailResponse { messageId = "m-1" }

        assertTrue(sender.sendEmail("bob@example.com", "Hello", "<p>hi</p>"))

        val req = captured.captured
        assertEquals("test@otterworks.io", req.source)
        assertEquals(listOf("bob@example.com"), req.destination!!.toAddresses)
        assertEquals(Content { data = "Hello"; charset = "UTF-8" }, req.message!!.subject)
        assertEquals(Content { data = "<p>hi</p>"; charset = "UTF-8" }, req.message!!.body!!.html)
    }

    @Test
    fun `sendEmail returns false when SES fails`() = runTest {
        coEvery { ses.sendEmail(any<SendEmailRequest>()) } throws RuntimeException("throttled")
        assertFalse(sender.sendEmail("bob@example.com", "Hello", "<p>hi</p>"))
    }
}
