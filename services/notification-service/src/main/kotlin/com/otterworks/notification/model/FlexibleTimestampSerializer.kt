package com.otterworks.notification.model

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant

/**
 * Accepts event timestamps as RFC 3339 strings or as Unix epoch numbers
 * (seconds or milliseconds, as emitted by older producers) and normalizes
 * them to an RFC 3339 string.
 */
object FlexibleTimestampSerializer : KSerializer<String> {
    // Epoch values at or above this are treated as milliseconds (~ year 2286 in seconds).
    private const val MILLIS_THRESHOLD = 10_000_000_000L

    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("FlexibleTimestamp", PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: String) = encoder.encodeString(value)

    override fun deserialize(decoder: Decoder): String {
        val raw = if (decoder is JsonDecoder) {
            when (val element = decoder.decodeJsonElement()) {
                is JsonNull -> return ""
                is JsonPrimitive -> element.content
                else -> throw SerializationException("timestamp must be a string or number, got $element")
            }
        } else {
            decoder.decodeString()
        }
        return normalize(raw)
    }

    fun normalize(raw: String): String {
        val trimmed = raw.trim()
        val epoch = trimmed.toBigDecimalOrNull() ?: return trimmed
        val epochMillis = if (epoch.abs() >= MILLIS_THRESHOLD.toBigDecimal()) {
            epoch.toLong()
        } else {
            epoch.movePointRight(3).toLong()
        }
        return Instant.ofEpochMilli(epochMillis).toString()
    }
}
