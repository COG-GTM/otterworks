package com.otterworks.notification.auth

import com.auth0.jwt.JWT
import com.auth0.jwt.JWTVerifier
import com.auth0.jwt.algorithms.Algorithm
import com.auth0.jwt.exceptions.JWTDecodeException
import com.auth0.jwt.exceptions.JWTVerificationException
import com.auth0.jwt.interfaces.Payload

/**
 * Verifies the HMAC-signed access tokens issued by auth-service with the shared JWT_SECRET,
 * mirroring the api-gateway's checks, so the caller's identity comes from a signed token and
 * never from a header, query parameter or path the caller chose.
 *
 * auth-service lets JJWT pick HS256/HS384/HS512 from the key length, so all three are accepted;
 * anything else (including `none`) is rejected. With no secret configured every token is rejected.
 */
class CallerTokenVerifier(secret: String?) {

    private val key: ByteArray? = secret?.takeIf { it.isNotBlank() }?.toByteArray(Charsets.UTF_8)

    val isConfigured: Boolean
        get() = key != null

    fun verifierFor(token: String): JWTVerifier? {
        val key = key ?: return null
        val algorithm = try {
            when (JWT.decode(token).algorithm) {
                "HS256" -> Algorithm.HMAC256(key)
                "HS384" -> Algorithm.HMAC384(key)
                "HS512" -> Algorithm.HMAC512(key)
                else -> return null
            }
        } catch (e: JWTDecodeException) {
            return null
        }
        return JWT.require(algorithm).build()
    }

    /** The caller's user ID: `sub`, falling back to `user_id` like the gateway. Refresh tokens are not callers. */
    fun userIdOf(payload: Payload): String? {
        val type = payload.getClaim("type").asString()
        if (type != null && type != "access") return null
        return payload.subject?.takeIf { it.isNotBlank() }
            ?: payload.getClaim("user_id").asString()?.takeIf { it.isNotBlank() }
    }

    fun verify(token: String): String? = try {
        verifierFor(token)?.verify(token)?.let(::userIdOf)
    } catch (e: JWTVerificationException) {
        null
    }
}
