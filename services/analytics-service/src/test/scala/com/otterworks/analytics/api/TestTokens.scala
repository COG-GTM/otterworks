package com.otterworks.analytics.api

import akka.http.scaladsl.model.headers.{Authorization, OAuth2BearerToken}
import io.jsonwebtoken.Jwts
import io.jsonwebtoken.security.Keys

import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.Date
import scala.jdk.CollectionConverters.*

/** Mints auth-service-shaped access tokens for route tests. */
object TestTokens:
  val Secret = "analytics-test-jwt-secret-at-least-thirty-two-bytes"
  private val key = Keys.hmacShaKeyFor(Secret.getBytes(StandardCharsets.UTF_8))

  val auth: AuthDirectives = AuthDirectives(JwtAuthenticator(Some(Secret)))

  def token(
      userId: String,
      roles: Seq[String] = Seq("USER"),
      tokenType: String = "access",
      expiresInSeconds: Long = 3600,
      signingKey: javax.crypto.SecretKey = key
  ): String =
    val now = Instant.now()
    Jwts.builder()
      .subject(userId)
      .claim("roles", roles.asJava)
      .claim("type", tokenType)
      .issuedAt(Date.from(now))
      .expiration(Date.from(now.plusSeconds(expiresInSeconds)))
      .signWith(signingKey)
      .compact()

  def bearer(token: String): Authorization = Authorization(OAuth2BearerToken(token))
  def user(userId: String): Authorization = bearer(token(userId))
  def admin(userId: String = "admin-1"): Authorization = bearer(token(userId, Seq("ADMIN")))
