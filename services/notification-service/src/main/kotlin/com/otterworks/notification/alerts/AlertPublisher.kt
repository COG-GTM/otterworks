package com.otterworks.notification.alerts

import com.otterworks.notification.config.AppConfig
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import mu.KotlinLogging
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration
import java.time.Instant
import java.util.concurrent.atomic.AtomicLong

private val logger = KotlinLogging.logger {}

/**
 * Fire-and-forget delivery of Grafana-shaped alerts to admin-service's
 * webhook ingest endpoint (`POST /api/v1/admin/alerts/ingest`), where they
 * become Incident records with an auto-triggered Devin session.
 *
 * The SQS consumer runs in a tight retry loop (failed messages re-enter the
 * queue after the visibility timeout), so alerts are rate-limited here and
 * the payload keeps admin-service's default dedup behavior: one open incident
 * per affected service, instead of one incident per failed poll or message.
 */
class AlertPublisher(
    private val adminServiceUrl: String,
    private val alertWebhookSecret: String?,
    private val minIntervalMs: Long = DEFAULT_MIN_INTERVAL_MS,
) {
    constructor(config: AppConfig) : this(config.adminServiceUrl, config.alertWebhookSecret)

    private val lastSentAtMs = AtomicLong(0)

    private val httpClient: HttpClient by lazy {
        HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build()
    }

    fun notifyConsumerFailure(error: String) {
        val now = System.currentTimeMillis()
        val last = lastSentAtMs.get()
        if (now - last < minIntervalMs || !lastSentAtMs.compareAndSet(last, now)) {
            return
        }

        val baseUrl = adminServiceUrl.trim().trimEnd('/')
        if (baseUrl.isEmpty()) {
            logger.warn { "ADMIN_SERVICE_URL is empty; skipping consumer-failure alert" }
            return
        }

        val payload = buildPayload(error).toString()
        val builder = HttpRequest.newBuilder()
            .uri(URI.create("$baseUrl/api/v1/admin/alerts/ingest"))
            .timeout(Duration.ofSeconds(10))
            .header("Content-Type", "application/json")
        alertWebhookSecret?.takeIf { it.isNotBlank() }?.let { builder.header("X-Alert-Secret", it) }
        val request = builder.POST(HttpRequest.BodyPublishers.ofString(payload)).build()

        httpClient.sendAsync(request, HttpResponse.BodyHandlers.discarding())
            .whenComplete { response, throwable ->
                when {
                    throwable != null ->
                        logger.warn(throwable) { "Failed to deliver consumer-failure alert to admin-service" }
                    response.statusCode() in 200..299 ->
                        logger.info { "Consumer-failure alert delivered to admin-service" }
                    else ->
                        logger.warn { "Consumer-failure alert rejected by admin-service (HTTP ${response.statusCode()})" }
                }
            }
    }

    internal fun buildPayload(error: String) = buildJsonObject {
        put("receiver", "otterworks-webhook")
        put("status", "firing")
        put(
            "alerts",
            buildJsonArray {
                add(
                    buildJsonObject {
                        put("status", "firing")
                        put(
                            "labels",
                            buildJsonObject {
                                put("alertname", "NotificationConsumerProcessingErrors")
                                put("severity", "critical")
                                put("affected_service", "notification-service")
                            }
                        )
                        put(
                            "annotations",
                            buildJsonObject {
                                put("summary", "Notification SQS consumer failing to process messages")
                                put(
                                    "description",
                                    "The notification-service SQS consumer is generating sustained " +
                                        "processing errors. Failed messages are not deleted from the " +
                                        "queue and re-enter after the SQS visibility timeout, so queue " +
                                        "depth grows unboundedly. Latest error: $error"
                                )
                            }
                        )
                        put("startsAt", Instant.now().toString())
                    }
                )
            }
        )
    }

    companion object {
        const val DEFAULT_MIN_INTERVAL_MS: Long = 60_000
    }
}
