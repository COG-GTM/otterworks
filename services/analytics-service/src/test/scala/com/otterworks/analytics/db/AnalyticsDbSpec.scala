package com.otterworks.analytics.db

import com.otterworks.analytics.config.PostgresConfig
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}
import slick.jdbc.PostgresProfile.api.*

/**
 * The analytics schema is pinned onto the JDBC URL, which has to work whether or
 * not the configured URL already carries query parameters.
 */
class AnalyticsDbSpec extends AnyFlatSpec with Matchers with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(20, Seconds), interval = Span(100, Millis))

  private def config(url: String) = PostgresConfig(url, "analytics", "analytics", 1)

  /** Nothing listens on port 1, so a query fails at connect time rather than at URL parse time. */
  private val unreachable = "jdbc:postgresql://localhost:1/analytics"

  private def assertConnectRefused(url: String): Unit =
    val db = new AnalyticsDb(config(url))
    try
      val failure = db.database.run(sql"SELECT 1".as[Int]).failed.futureValue
      failure shouldBe a[java.sql.SQLException]
      failure.getMessage should include("Connection to localhost:1 refused")
    finally db.close()

  "AnalyticsDb" should "build a usable handle for a URL without query parameters" in {
    assertConnectRefused(unreachable)
  }

  it should "build a usable handle for a URL that already has query parameters" in {
    assertConnectRefused(s"$unreachable?ApplicationName=analytics-service")
  }

  it should "be closeable twice without error" in {
    val db = new AnalyticsDb(config(unreachable))
    db.close()
    noException should be thrownBy db.close()
  }
