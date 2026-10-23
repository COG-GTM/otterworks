package com.otterworks.notification.auth

import com.auth0.jwt.JWT
import com.auth0.jwt.algorithms.Algorithm
import java.util.Date
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

class AccessTokenVerifierTest {

    private val secret = "test-secret-that-is-long-enough-for-hs512-signing-0123456789abcdef"
    private val verifier = AccessTokenVerifier(secret)
    private val future = Date(System.currentTimeMillis() + 60_000)

    @Test
    fun `accepts auth-service style access tokens across the HMAC family`() {
        listOf(Algorithm.HMAC256(secret), Algorithm.HMAC384(secret), Algorithm.HMAC512(secret)).forEach { alg ->
            val token = JWT.create().withSubject("u-1").withClaim("type", "access").withExpiresAt(future).sign(alg)
            assertEquals("u-1", verifier.verify(token)?.subject)
        }
    }

    @Test
    fun `rejects refresh, unsigned, unsubjected, non-expiring and malformed tokens`() {
        val refresh = JWT.create().withSubject("u-1").withClaim("type", "refresh").withExpiresAt(future)
            .sign(Algorithm.HMAC256(secret))
        val none = JWT.create().withSubject("u-1").withExpiresAt(future).sign(Algorithm.none())
        val noSub = JWT.create().withClaim("type", "access").withExpiresAt(future).sign(Algorithm.HMAC256(secret))
        val noExp = JWT.create().withSubject("u-1").sign(Algorithm.HMAC256(secret))

        listOf(refresh, none, noSub, noExp, "not-a-jwt", "").forEach { assertNull(verifier.verify(it), it) }
    }

    @Test
    fun `refuses to start without a secret`() {
        assertFailsWith<IllegalArgumentException> { AccessTokenVerifier(" ") }
    }
}
