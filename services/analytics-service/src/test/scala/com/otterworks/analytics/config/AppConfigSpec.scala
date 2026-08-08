package com.otterworks.analytics.config

import com.typesafe.config.ConfigFactory
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

/** Covers the typed config wrapper: explicit values, optional paths and defaults. */
class AppConfigSpec extends AnyFlatSpec with Matchers:

  private val fullConfig = ConfigFactory.parseString(
    """
      |analytics {
      |  s3.data-lake-bucket = "otterworks-lake"
      |  sqs.events-queue-url = "http://sqs.local/000000000000/analytics-events"
      |  aws {
      |    region = "eu-west-1"
      |    endpoint-url = "http://localhost:4566"
      |  }
      |  postgres {
      |    url = "jdbc:postgresql://db:5432/analytics"
      |    user = "analytics"
      |    password = "s3cret"
      |    max-pool-size = 7
      |  }
      |  repository.backend = "in-memory"
      |  server {
      |    host = "127.0.0.1"
      |    port = 9099
      |  }
      |}
      |""".stripMargin
  )

  private val minimalConfig = ConfigFactory.parseString(
    """
      |analytics {
      |  s3.data-lake-bucket = "bucket"
      |  sqs.events-queue-url = "http://sqs.local/queue"
      |  aws.region = "us-east-2"
      |  postgres {
      |    url = "jdbc:postgresql://db:5432/analytics"
      |    user = "u"
      |    password = "p"
      |    max-pool-size = 1
      |  }
      |}
      |""".stripMargin
  )

  "AppConfig.fromConfig" should "read every explicitly configured value" in {
    val config = AppConfig.fromConfig(fullConfig)

    config.s3.dataLakeBucket shouldBe "otterworks-lake"
    config.sqs.eventsQueueUrl shouldBe "http://sqs.local/000000000000/analytics-events"
    config.aws.region shouldBe "eu-west-1"
    config.aws.endpointUrl shouldBe Some("http://localhost:4566")
    config.postgres shouldBe PostgresConfig("jdbc:postgresql://db:5432/analytics", "analytics", "s3cret", 7)
    config.repository.backend shouldBe "in-memory"
    config.server shouldBe ServerConfig("127.0.0.1", 9099)
  }

  it should "fall back to the golden defaults for every optional path" in {
    val config = AppConfig.fromConfig(minimalConfig)

    config.aws.endpointUrl shouldBe None
    config.repository.backend shouldBe "postgres"
    config.repository.isPostgres shouldBe true
    config.server shouldBe ServerConfig("0.0.0.0", 8088)
  }

  "AppConfig.load" should "read the application.conf on the classpath" in {
    val config = AppConfig.load()

    config.s3.dataLakeBucket shouldBe "test-data-lake"
    config.aws.region shouldBe "us-east-1"
    config.repository.backend shouldBe "in-memory"
    config.repository.isPostgres shouldBe false
    config.server.port shouldBe 8088
    config.postgres.maxPoolSize shouldBe 2
  }

  "RepositoryConfig.isPostgres" should "match the backend name case- and whitespace-insensitively" in {
    RepositoryConfig("postgres").isPostgres shouldBe true
    RepositoryConfig("  Postgres ").isPostgres shouldBe true
    RepositoryConfig("POSTGRES").isPostgres shouldBe true
    RepositoryConfig("in-memory").isPostgres shouldBe false
    RepositoryConfig("").isPostgres shouldBe false
  }
