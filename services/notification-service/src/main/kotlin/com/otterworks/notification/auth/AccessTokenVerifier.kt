package com.otterworks.notification.auth

import com.auth0.jwt.JWT
import com.auth0.jwt.JWTVerifier
import com.auth0.jwt.algorithms.Algorithm
import com.auth0.jwt.exceptions.JWTVerificationException
import com.auth0.jwt.interfaces.DecodedJWT

/**
 * Verifies access tokens issued by auth-service, which signs with the shared
 * JWT_SECRET (HS256/HS384/HS512 depending on key length, chosen by jjwt).
 * Only the HMAC family is accepted; refresh tokens and tokens without a
 * subject or expiry are rejected.
 */
class AccessTokenVerifier(secret: String) {

    init {
        require(secret.isNotBlank()) { "JWT_SECRET must be set for notification-service" }
    }

    private val verifiers: Map<String, JWTVerifier> = mapOf(
        "HS256" to build(Algorithm.HMAC256(secret)),
        "HS384" to build(Algorithm.HMAC384(secret)),
        "HS512" to build(Algorithm.HMAC512(secret)),
    )

    fun verifierFor(token: String): JWTVerifier? = try {
        verifiers[JWT.decode(token).algorithm]
    } catch (_: JWTVerificationException) {
        null
    }

    fun verify(token: String): DecodedJWT? = try {
        verifierFor(token)?.verify(token)
    } catch (_: JWTVerificationException) {
        null
    }

    private fun build(algorithm: Algorithm): JWTVerifier =
        JWT.require(algorithm)
            .withClaimPresence("sub")
            .withClaimPresence("exp")
            .withClaim("type") { claim, _ -> claim.isMissing || claim.isNull || claim.asString() == ACCESS_TOKEN_TYPE }
            .build()

    companion object {
        const val ACCESS_TOKEN_TYPE = "access"
    }
}
