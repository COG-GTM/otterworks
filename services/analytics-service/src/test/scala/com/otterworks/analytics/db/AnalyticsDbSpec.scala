package com.otterworks.analytics.db

import com.otterworks.analytics.config.PostgresConfig
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

/**
 * The handle pins every connection to the service-owned `analytics` schema. Slick opens
 * connections lazily, so building the handle contacts no database.
 */
class AnalyticsDbSpec extends AnyFlatSpec with Matchers:

  /** The effective JDBC url Slick will dial, without opening a connection. */
  private def urlOf(jdbcUrl: String): String =
    val db = new AnalyticsDb(PostgresConfig(jdbcUrl, "user", "pass", 2))
    try
      db.database.source match
        case source: slick.jdbc.DataSourceJdbcDataSource =>
          source.ds match
            case driverSource: slick.jdbc.DriverDataSource => driverSource.getUrl
            case other => fail(s"unexpected Slick DataSource: $other")
        case other => fail(s"unexpected Slick JdbcDataSource: $other")
    finally db.close()

  "AnalyticsDb" should "append currentSchema with a query separator for a bare JDBC url" in {
    urlOf("jdbc:postgresql://localhost:5432/analytics") shouldBe
      "jdbc:postgresql://localhost:5432/analytics?currentSchema=analytics"
  }

  it should "append currentSchema as an extra parameter when the url already has a query" in {
    urlOf("jdbc:postgresql://localhost:5432/analytics?ssl=true") shouldBe
      "jdbc:postgresql://localhost:5432/analytics?ssl=true&currentSchema=analytics"
  }

  it should "close cleanly without ever opening a connection" in {
    val db = new AnalyticsDb(PostgresConfig("jdbc:postgresql://localhost:5432/analytics", "u", "p", 1))
    noException should be thrownBy db.close()
  }
