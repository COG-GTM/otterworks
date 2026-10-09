package com.otterworks.notification.auth

import com.auth0.jwt.JWT
import com.auth0.jwt.JWTVerifier
import com.auth0.jwt.algorithms.Algorithm
import com.auth0.jwt.exceptions.JWTDecodeException
import com.auth0.jwt.interfaces.Payload
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.auth.HttpAuthHeader
import io.ktor.server.application.Application
import io.ktor.server.application.ApplicationCall
import io.ktor.server.application.call
import io.ktor.server.application.install
import io.ktor.server.auth.Authentication
import io.ktor.server.auth.Principal
import io.ktor.server.auth.jwt.jwt
import io.ktor.server.auth.parseAuthorizationHeader
import io.ktor.server.auth.principal
import io.ktor.server.response.respond
import kotlinx.serialization.Serializable
import mu.KotlinLogging

private val logger = KotlinLogging.logger {}

const val JWT_AUTH = "otterworks-jwt"

/**
 * Browsers cannot set headers on a WebSocket handshake, so the socket carries its
 * access token as a subprotocol pair: `Sec-WebSocket-Protocol: bearer, <token>`.
 */
const val WS_BEARER_PROTOCOL = "bearer"

data class UserPrincipal(val userId: String) : Principal

@Serializable
data class AuthErrorResponse(val error: String)

val ApplicationCall.authenticatedUserId: String
    get() = requireNotNull(principal<UserPrincipal>()) { "route is not behind authenticate($JWT_AUTH)" }.userId

/**
 * Validates the auth-service access token on every user-scoped route, so identity
 * never comes from a header or parameter a direct caller could choose. auth-service
 * signs with jjwt's `Keys.hmacShaKeyFor`, which picks HS256/384/512 by secret length,
 * so all three HMAC variants are accepted; anything else is rejected.
 */
fun Application.configureAuthentication(jwtSecret: String?) {
    if (jwtSecret == null) {
        logger.error { "JWT_SECRET is not set: every authenticated route will answer 401" }
    }
    val verifiers = jwtSecret?.let { secret ->
        mapOf(
            "HS256" to JWT.require(Algorithm.HMAC256(secret)).build(),
            "HS384" to JWT.require(Algorithm.HMAC384(secret)).build(),
            "HS512" to JWT.require(Algorithm.HMAC512(secret)).build(),
        )
    }.orEmpty()

    install(Authentication) {
        jwt(JWT_AUTH) {
            realm = "otterworks"
            authHeader { call -> bearerHeader(call) }
            verifier { header -> verifierFor(header, verifiers) }
            validate { credential -> principalOf(credential.payload) }
            challenge { _, _ ->
                call.respond(HttpStatusCode.Unauthorized, AuthErrorResponse("missing or invalid bearer token"))
            }
        }
    }
}

internal fun principalOf(payload: Payload): UserPrincipal? {
    if (payload.getClaim("type").asString() == "refresh") return null
    val userId = payload.subject?.takeIf { it.isNotBlank() }
        ?: payload.getClaim("user_id").asString()?.takeIf { it.isNotBlank() }
        ?: return null
    return UserPrincipal(userId)
}

private fun verifierFor(header: HttpAuthHeader, verifiers: Map<String, JWTVerifier>): JWTVerifier? {
    val token = (header as? HttpAuthHeader.Single)?.blob ?: return null
    return try {
        verifiers[JWT.decode(token).algorithm]
    } catch (e: JWTDecodeException) {
        null
    }
}

private fun bearerHeader(call: ApplicationCall): HttpAuthHeader? {
    val authorization = try {
        call.request.parseAuthorizationHeader()
    } catch (e: IllegalArgumentException) {
        null
    }
    if (authorization != null) return authorization
    val token = webSocketProtocolToken(call) ?: return null
    return HttpAuthHeader.Single("Bearer", token)
}

private fun webSocketProtocolToken(call: ApplicationCall): String? {
    val offered = call.request.headers.getAll(HttpHeaders.SecWebSocketProtocol)
        ?.flatMap { it.split(',') }
        ?.map { it.trim() }
        ?.filter { it.isNotEmpty() }
        ?: return null
    val marker = offered.indexOf(WS_BEARER_PROTOCOL)
    return offered.getOrNull(marker + 1)?.takeIf { marker >= 0 }
}
