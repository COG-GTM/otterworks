package com.otterworks.notification.consumer

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class RedisSettingsTest {
    @Test
    fun `defaults to unauthenticated plaintext localhost`() {
        val settings = redisSettingsFrom { null }

        assertEquals("localhost", settings.host)
        assertEquals(6379, settings.port)
        assertNull(settings.password)
        assertFalse(settings.ssl)
    }

    @Test
    fun `uses AUTH token and TLS for the shared ElastiCache`() {
        val env = mapOf(
            "REDIS_HOST" to "master.otterworks-redis-dev.cache.amazonaws.com",
            "REDIS_PORT" to "6379",
            "REDIS_PASSWORD" to "s3cret",
            "REDIS_TLS" to "true",
        )

        val settings = redisSettingsFrom(env::get)

        assertEquals("master.otterworks-redis-dev.cache.amazonaws.com", settings.host)
        assertEquals("s3cret", settings.password)
        assertTrue(settings.ssl)
    }

    @Test
    fun `treats an empty password as no AUTH`() {
        assertNull(redisSettingsFrom(mapOf("REDIS_PASSWORD" to "")::get).password)
    }
}
