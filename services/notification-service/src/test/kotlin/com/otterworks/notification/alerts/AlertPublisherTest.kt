package com.otterworks.notification.alerts

import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class AlertPublisherTest {

    @Test
    fun `payload has Grafana shape without dedup opt-out`() {
        val publisher = AlertPublisher("http://admin-service:8089", null)
        val payload = publisher.buildPayload("QueueDoesNotExist")

        assertEquals("firing", payload["status"]!!.jsonPrimitive.content)
        val alert = payload["alerts"]!!.jsonArray[0].jsonObject
        assertEquals("firing", alert["status"]!!.jsonPrimitive.content)
        val labels = alert["labels"]!!.jsonObject
        assertEquals("NotificationConsumerProcessingErrors", labels["alertname"]!!.jsonPrimitive.content)
        assertEquals("critical", labels["severity"]!!.jsonPrimitive.content)
        assertEquals("notification-service", labels["affected_service"]!!.jsonPrimitive.content)
        // The consumer retries failed messages forever, so admin-service's
        // default open-incident dedup must stay in effect (no dedup=false).
        assertEquals(null, labels["dedup"])
        val annotations = alert["annotations"]!!.jsonObject
        assertEquals(
            "Notification SQS consumer failing to process messages",
            annotations["summary"]!!.jsonPrimitive.content
        )
        assertTrue(annotations["description"]!!.jsonPrimitive.content.contains("QueueDoesNotExist"))
        assertTrue(alert["startsAt"]!!.jsonPrimitive.content.isNotBlank())
    }

    @Test
    fun `empty admin service url skips without sending`() {
        val publisher = AlertPublisher("   ", "secret")
        publisher.notifyConsumerFailure("boom")
    }

    @Test
    fun `unreachable admin service does not throw`() {
        val publisher = AlertPublisher("http://127.0.0.1:1", "secret")
        publisher.notifyConsumerFailure("boom")
    }
}
