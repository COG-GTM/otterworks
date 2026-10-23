package com.otterworks.notification.auth

import io.ktor.http.HttpStatusCode
import io.ktor.http.auth.HttpAuthHeader
import io.ktor.http.auth.parseAuthorizationHeader
import io.ktor.server.application.Application
import io.ktor.server.application.ApplicationCall
import io.ktor.server.application.install
import io.ktor.server.auth.Authentication
import io.ktor.server.auth.jwt.JWTPrincipal
import io.ktor.server.auth.jwt.jwt
import io.ktor.server.auth.principal
import io.ktor.server.response.respond
import kotlinx.serialization.Serializable

const val JWT_AUTH = "otterworks-jwt"

@Serializable
private data class AuthErrorResponse(val error: String)

/**
 * Identity comes only from a verified bearer token; X-User-ID headers and
 * user_id parameters are never trusted, so a caller that reaches the service
 * port directly cannot impersonate anyone.
 */
fun Application.configureAuthentication(jwtSecret: String) {
    val tokens = AccessTokenVerifier(jwtSecret)

    install(Authentication) {
        jwt(JWT_AUTH) {
            realm = "otterworks"
            authHeader { call ->
                try {
                    call.request.parseAuthorizationHeader()
                } catch (_: IllegalArgumentException) {
                    null
                }
            }
            verifier { header ->
                val token = (header as? HttpAuthHeader.Single)
                    ?.takeIf { it.authScheme.equals("Bearer", ignoreCase = true) }
                    ?.blob
                token?.let { tokens.verifierFor(it) }
            }
            validate { credential ->
                credential.payload.subject?.takeIf { it.isNotBlank() }?.let { JWTPrincipal(credential.payload) }
            }
            challenge { _, _ ->
                call.respond(HttpStatusCode.Unauthorized, AuthErrorResponse("missing or invalid bearer token"))
            }
        }
    }
}

/** The authenticated caller's user id (the token's `sub` claim). */
fun ApplicationCall.callerUserId(): String =
    principal<JWTPrincipal>()?.subject ?: error("callerUserId() used outside an authenticate block")
