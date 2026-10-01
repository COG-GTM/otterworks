package com.otterworks.analytics

import com.otterworks.analytics.api.HealthRoutes
import com.typesafe.config.ConfigFactory
import org.scalatest.BeforeAndAfterAll
import org.scalatest.concurrent.Eventually
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import java.io.InputStream
import java.net.{HttpURLConnection, InetAddress, ServerSocket, URI}
import java.nio.charset.StandardCharsets

/**
 * Boots the real service entrypoint on a loopback port. Everything it depends on is either
 * in-process (in-memory metrics store) or deliberately unreachable (a closed loopback port for
 * PostgreSQL and SQS), so the bootstrap wiring — including its fallback and failure arms — is
 * exercised without a database, AWS or any off-box traffic.
 */
class MainSpec extends AnyFlatSpec with Matchers with BeforeAndAfterAll with Eventually:

  given PatienceConfig = PatienceConfig(timeout = Span(60, Seconds), interval = Span(500, Millis))

  private val touchedProperties = List(
    "akka.daemonic",
    "analytics.server.host",
    "analytics.server.port",
    "analytics.repository.backend",
    "analytics.postgres.url",
    "analytics.sqs.events-queue-url",
    "analytics.aws.endpoint-url"
  )
  private val savedProperties = touchedProperties.map(k => k -> Option(System.getProperty(k))).toMap

  /** A loopback port with nothing listening on it: connections are refused immediately. */
  private val deadPort = freePort()

  override def beforeAll(): Unit =
    // Akka's threads are non-daemon by default; the bootstrapped systems outlive the test
    // (Main only returns once its system terminates) and would otherwise keep the JVM alive.
    System.setProperty("akka.daemonic", "on")
    System.setProperty("analytics.server.host", "127.0.0.1")
    System.setProperty("analytics.aws.endpoint-url", s"http://127.0.0.1:$deadPort")
    System.setProperty("analytics.sqs.events-queue-url", s"http://127.0.0.1:$deadPort/queue/events")

  override def afterAll(): Unit =
    savedProperties.foreach { (key, value) =>
      value.fold(System.clearProperty(key))(System.setProperty(key, _)): Unit
    }
    ConfigFactory.invalidateCaches()

  private def freePort(): Int =
    val socket = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
    try socket.getLocalPort
    finally socket.close()

  private def startMain(port: Int, backend: String, postgresUrl: String): Thread =
    System.setProperty("analytics.server.port", port.toString)
    System.setProperty("analytics.repository.backend", backend)
    System.setProperty("analytics.postgres.url", postgresUrl)
    ConfigFactory.invalidateCaches()
    val thread = Thread(() => Main.main(Array.empty), s"main-spec-$port")
    thread.setDaemon(true)
    thread.start()
    thread

  private case class Response(status: Int, body: String)

  private def get(port: Int, path: String): Response =
    val connection = URI.create(s"http://127.0.0.1:$port$path").toURL
      .openConnection().asInstanceOf[HttpURLConnection]
    connection.setConnectTimeout(2000)
    connection.setReadTimeout(5000)
    try
      val status = connection.getResponseCode
      val stream: InputStream =
        Option(connection.getErrorStream).getOrElse(connection.getInputStream)
      Response(status, new String(stream.readAllBytes(), StandardCharsets.UTF_8))
    finally connection.disconnect()

  "Main" should "serve health and analytics routes on the configured port with the in-memory store" in {
    val port = freePort()
    startMain(port, backend = "in-memory", postgresUrl = "jdbc:postgresql://127.0.0.1:5432/unused")

    eventually {
      get(port, "/health").status shouldBe 200
    }
    get(port, "/health").body should include(""""status":"healthy"""")
    get(port, "/api/v1/analytics/dashboard").status shouldBe 200

    // The Prometheus collectors live in the companion object, which universal-apply of the
    // class never initialises: touch one so the exposition output is not empty.
    HealthRoutes.eventsReceivedTotal.labels("document.created").inc()
    get(port, "/metrics").body should include("analytics_events_received_total")
  }

  it should "answer 503 on the margin and market routes when there is no durable store" in {
    val port = freePort()
    startMain(port, backend = "in-memory", postgresUrl = "jdbc:postgresql://127.0.0.1:5432/unused")

    eventually {
      get(port, "/health").status shouldBe 200
    }
    val margins = get(port, "/api/v1/analytics/margins")
    margins.status shouldBe 503
    margins.body should include("require the durable PostgreSQL store")
    get(port, "/api/v1/analytics/market/status").status shouldBe 503
  }

  it should "fall back to the in-memory store when the durable PostgreSQL store cannot migrate" in {
    val port = freePort()
    // `postgres` backend selected, but nothing is listening: the Flyway migration throws and
    // Main must degrade to the in-memory store instead of failing to boot.
    startMain(port, backend = "postgres", postgresUrl = s"jdbc:postgresql://127.0.0.1:$deadPort/nope")

    eventually {
      get(port, "/health").status shouldBe 200
    }
    get(port, "/health").body should include(""""status":"healthy"""")
    get(port, "/api/v1/analytics/margins").status shouldBe 503
  }

  it should "terminate instead of hanging when the server port is already taken" in {
    val occupied = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
    try
      val thread = startMain(
        occupied.getLocalPort,
        backend = "in-memory",
        postgresUrl = "jdbc:postgresql://127.0.0.1:5432/unused")
      thread.join(60000)
      thread.isAlive shouldBe false // the bind failed, the system terminated and main returned
    finally occupied.close()
  }
