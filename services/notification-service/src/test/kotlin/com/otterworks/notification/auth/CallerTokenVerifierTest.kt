package com.otterworks.notification.auth

import com.auth0.jwt.JWT
import com.auth0.jwt.algorithms.Algorithm
import java.util.Base64
import java.util.Date
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull

class CallerTokenVerifierTest {

    private val secret = "notification-test-jwt-secret-0123456789abcdef"
    private val verifier = CallerTokenVerifier(secret)
    private fun inAMinute() = Date(System.currentTimeMillis() + 60_000)

    @Test
    fun `accepts every HMAC size auth-service can sign with`() {
        for (algorithm in listOf(Algorithm.HMAC256(secret), Algorithm.HMAC384(secret), Algorithm.HMAC512(secret))) {
            val token = JWT.create().withSubject("alice").withExpiresAt(inAMinute()).sign(algorithm)
            assertEquals("alice", verifier.verify(token), algorithm.name)
        }
    }

    @Test
    fun `falls back to the user_id claim like the gateway`() {
        val token = JWT.create().withClaim("user_id", "bob").withExpiresAt(inAMinute()).sign(Algorithm.HMAC256(secret))
        assertEquals("bob", verifier.verify(token))
    }

    @Test
    fun `rejects a token signed with another secret`() {
        val token = JWT.create().withSubject("alice").sign(Algorithm.HMAC384("some-other-secret-0123456789abcdef"))
        assertNull(verifier.verify(token))
    }

    @Test
    fun `rejects an unsigned alg none token`() {
        val encoder = Base64.getUrlEncoder().withoutPadding()
        val header = encoder.encodeToString("""{"alg":"none","typ":"JWT"}""".toByteArray())
        val payload = encoder.encodeToString("""{"sub":"alice"}""".toByteArray())
        assertNull(verifier.verify("$header.$payload."))
    }

    @Test
    fun `rejects an expired token`() {
        val token = JWT.create().withSubject("alice")
            .withExpiresAt(Date(System.currentTimeMillis() - 60_000))
            .sign(Algorithm.HMAC384(secret))
        assertNull(verifier.verify(token))
    }

    @Test
    fun `rejects refresh tokens and tokens without an identity`() {
        val refresh = JWT.create().withSubject("alice").withClaim("type", "refresh").sign(Algorithm.HMAC384(secret))
        val anonymous = JWT.create().withExpiresAt(inAMinute()).sign(Algorithm.HMAC384(secret))
        assertNull(verifier.verify(refresh))
        assertNull(verifier.verify(anonymous))
    }

    @Test
    fun `rejects garbage`() {
        assertNull(verifier.verify("not-a-jwt"))
    }

    @Test
    fun `rejects everything when no secret is configured`() {
        val unconfigured = CallerTokenVerifier(null)
        val token = JWT.create().withSubject("alice").sign(Algorithm.HMAC384(secret))
        assertFalse(unconfigured.isConfigured)
        assertNull(unconfigured.verify(token))
        assertNull(CallerTokenVerifier("  ").verify(token))
    }
}
