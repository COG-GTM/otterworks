package com.otterworks.notification.auth

import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.routes.ErrorResponse
import io.ktor.http.HttpStatusCode
import io.ktor.http.auth.HttpAuthHeader
import io.ktor.server.application.Application
import io.ktor.server.application.ApplicationCall
import io.ktor.server.application.install
import io.ktor.server.auth.Authentication
import io.ktor.server.auth.Principal
import io.ktor.server.auth.jwt.jwt
import io.ktor.server.auth.principal
import io.ktor.server.response.respond
import mu.KotlinLogging

private val logger = KotlinLogging.logger {}

const val CALLER_AUTH = "caller-jwt"

data class CallerPrincipal(val userId: String) : Principal

/** Authenticated caller's user ID; only valid inside `authenticate(CALLER_AUTH)`. */
val ApplicationCall.callerId: String
    get() = checkNotNull(principal<CallerPrincipal>()) { "route is not behind authenticate($CALLER_AUTH)" }.userId

fun Application.configureAuthentication(config: AppConfig) {
    val tokens = CallerTokenVerifier(config.jwtSecret)
    if (!tokens.isConfigured) {
        logger.error { "JWT_SECRET is not set: every /api/v1 and /ws request will be rejected with 401" }
    }

    install(Authentication) {
        jwt(CALLER_AUTH) {
            realm = "otterworks"
            verifier { header ->
                (header as? HttpAuthHeader.Single)
                    ?.takeIf { it.authScheme.equals("Bearer", ignoreCase = true) }
                    ?.let { tokens.verifierFor(it.blob) }
            }
            validate { credential -> tokens.userIdOf(credential.payload)?.let(::CallerPrincipal) }
            challenge { _, _ ->
                call.respond(HttpStatusCode.Unauthorized, ErrorResponse("a valid bearer token is required"))
            }
        }
    }
}
