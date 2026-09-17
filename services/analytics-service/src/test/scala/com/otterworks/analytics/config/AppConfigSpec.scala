package com.otterworks.analytics.config

import com.typesafe.config.ConfigFactory
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

/** Typed-config mapping, including every optional path and its fallback. */
class AppConfigSpec extends AnyFlatSpec with Matchers:

  private val full = ConfigFactory.parseString(
    """
      |analytics {
      |  s3.data-lake-bucket = "lake-bucket"
      |  sqs.events-queue-url = "http://sqs.local/000/events"
      |  aws {
      |    region = "eu-west-1"
      |    endpoint-url = "http://localhost:4566"
      |  }
      |  postgres {
      |    url = "jdbc:postgresql://db:5432/analytics"
      |    user = "analytics"
      |    password = "s3cret"
      |    max-pool-size = 9
      |  }
      |  repository.backend = "in-memory"
      |  server {
      |    host = "127.0.0.1"
      |    port = 9099
      |  }
      |}
      |""".stripMargin
  )

  private val minimal = ConfigFactory.parseString(
    """
      |analytics {
      |  s3.data-lake-bucket = "lake-bucket"
      |  sqs.events-queue-url = "http://sqs.local/000/events"
      |  aws.region = "us-east-1"
      |  postgres {
      |    url = "jdbc:postgresql://db:5432/analytics"
      |    user = "analytics"
      |    password = "s3cret"
      |    max-pool-size = 2
      |  }
      |}
      |""".stripMargin
  )

  "AppConfig.fromConfig" should "map every configured value" in {
    val config = AppConfig.fromConfig(full)

    config.s3.dataLakeBucket shouldBe "lake-bucket"
    config.sqs.eventsQueueUrl shouldBe "http://sqs.local/000/events"
    config.aws.region shouldBe "eu-west-1"
    config.aws.endpointUrl shouldBe Some("http://localhost:4566")
    config.postgres shouldBe PostgresConfig("jdbc:postgresql://db:5432/analytics", "analytics", "s3cret", 9)
    config.repository.backend shouldBe "in-memory"
    config.server shouldBe ServerConfig("127.0.0.1", 9099)
  }

  it should "fall back to the documented defaults for optional paths" in {
    val config = AppConfig.fromConfig(minimal)

    config.aws.endpointUrl shouldBe None
    config.repository.backend shouldBe "postgres"
    config.server.host shouldBe "0.0.0.0"
    config.server.port shouldBe 8088
  }

  "AppConfig.load" should "read the ambient application.conf" in {
    val config = AppConfig.load()

    config.s3.dataLakeBucket shouldBe "test-data-lake"
    config.repository.backend shouldBe "in-memory"
    config.server.port shouldBe 8088
    config.postgres.maxPoolSize shouldBe 2
  }

  "RepositoryConfig.isPostgres" should "match the backend name case- and whitespace-insensitively" in {
    RepositoryConfig("postgres").isPostgres shouldBe true
    RepositoryConfig("  POSTGRES ").isPostgres shouldBe true
    RepositoryConfig("in-memory").isPostgres shouldBe false
  }
