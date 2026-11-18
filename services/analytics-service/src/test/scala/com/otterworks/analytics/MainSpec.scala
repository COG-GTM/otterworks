package com.otterworks.analytics

import com.dimafeng.testcontainers.PostgreSQLContainer
import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.db.AnalyticsDb
import com.typesafe.config.ConfigFactory
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.testcontainers.utility.DockerImageName
import slick.jdbc.PostgresProfile.api.*

import java.net.{InetAddress, ServerSocket}
import scala.concurrent.{Await, ExecutionContext, Future}
import scala.concurrent.duration.*

/**
 * Boot-path smoke tests for Main. The configured port is held open so the HTTP
 * bind fails, which makes Main terminate its actor system and return.
 */
class MainSpec extends AnyFlatSpec with Matchers:

  private def runMainUntilBindFails(props: Map[String, String]): Unit =
    val blocker = new ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
    val all = props ++ Map(
      "analytics.server.host" -> "127.0.0.1",
      "analytics.server.port" -> blocker.getLocalPort.toString
    )
    try
      all.foreach((k, v) => System.setProperty(k, v))
      ConfigFactory.invalidateCaches()
      Await.result(Future(Main.main(Array.empty))(using ExecutionContext.global), 90.seconds)
    finally
      all.keys.foreach(System.clearProperty)
      ConfigFactory.invalidateCaches()
      blocker.close()

  "Main" should "wire the in-memory store and shut down when the port cannot be bound" in {
    noException should be thrownBy runMainUntilBindFails(Map("analytics.repository.backend" -> "in-memory"))
  }

  it should "fall back to the in-memory store when PostgreSQL is unreachable" in {
    noException should be thrownBy runMainUntilBindFails(Map(
      "analytics.repository.backend" -> "postgres",
      "analytics.postgres.url" -> "jdbc:postgresql://127.0.0.1:1/unreachable"
    ))
  }

  it should "migrate and seed the market baseline when PostgreSQL is available" in {
    val container =
      try
        val c = PostgreSQLContainer(dockerImageNameOverride = DockerImageName.parse("postgres:15-alpine"))
        c.start()
        Some(c)
      catch case _: Throwable => None
    assume(container.isDefined, "Docker not available")
    val c = container.get
    try
      runMainUntilBindFails(Map(
        "analytics.repository.backend" -> "postgres",
        "analytics.postgres.url" -> c.jdbcUrl,
        "analytics.postgres.user" -> c.username,
        "analytics.postgres.password" -> c.password
      ))
      val db = new AnalyticsDb(PostgresConfig(c.jdbcUrl, c.username, c.password, 1))
      try
        val products = Await.result(db.database.run(sql"SELECT COUNT(*) FROM products".as[Long].head), 30.seconds)
        products shouldBe 40L
      finally db.close()
    finally c.stop()
  }
