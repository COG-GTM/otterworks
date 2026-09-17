package com.otterworks.analytics.repository

import com.otterworks.analytics.config.PostgresConfig
import com.otterworks.analytics.db.AnalyticsDb
import org.scalatest.concurrent.ScalaFutures
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers
import org.scalatest.time.{Millis, Seconds, Span}

import scala.concurrent.ExecutionContext

/** Short-circuit behaviour of the market repository (the query paths need a live database). */
class MarketRepositorySpec extends AnyFlatSpec with Matchers with ScalaFutures:

  given PatienceConfig = PatienceConfig(timeout = Span(5, Seconds), interval = Span(50, Millis))
  given ExecutionContext = ExecutionContext.global

  private def withRepository[A](f: MarketRepository => A): A =
    val db = new AnalyticsDb(PostgresConfig("jdbc:postgresql://localhost:5432/analytics", "u", "p", 1))
    try f(new MarketRepository(db))
    finally db.close()

  "pricesForSeries" should "return nothing without querying when the series set is empty" in {
    withRepository { repo =>
      repo.pricesForSeries(Seq.empty).futureValue shouldBe empty
    }
  }
