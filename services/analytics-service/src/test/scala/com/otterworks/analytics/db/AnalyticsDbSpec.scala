package com.otterworks.analytics.db

import com.otterworks.analytics.config.PostgresConfig
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import slick.jdbc.{DataSourceJdbcDataSource, DriverDataSource}

/**
 * The JDBC URL is assembled eagerly at construction time (no connection is opened
 * until a query runs), so the schema-pinning logic can be checked without a database.
 */
class AnalyticsDbSpec extends AnyFlatSpec with Matchers:

  private def jdbcUrlOf(url: String): String =
    val db = new AnalyticsDb(PostgresConfig(url, "u", "p", maxPoolSize = 1))
    try
      db.database.source match
        case source: DataSourceJdbcDataSource =>
          source.ds match
            case driver: DriverDataSource => driver.url
            case other                    => fail(s"unexpected DataSource: $other")
        case other => fail(s"unexpected JdbcDataSource: $other")
    finally db.close()

  "AnalyticsDb" should "pin the analytics schema on a URL without a query string" in {
    jdbcUrlOf("jdbc:postgresql://localhost:5432/analytics") shouldBe
      "jdbc:postgresql://localhost:5432/analytics?currentSchema=analytics"
  }

  it should "append the schema to a URL that already carries parameters" in {
    jdbcUrlOf("jdbc:postgresql://localhost:5432/analytics?sslmode=require") shouldBe
      "jdbc:postgresql://localhost:5432/analytics?sslmode=require&currentSchema=analytics"
  }
