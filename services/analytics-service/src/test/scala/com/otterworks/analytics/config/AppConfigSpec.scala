package com.otterworks.analytics.config

import com.typesafe.config.ConfigFactory
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

class AppConfigSpec extends AnyFlatSpec with Matchers:

  private val required =
    """analytics {
      |  s3.data-lake-bucket = "lake"
      |  sqs.events-queue-url = "http://sqs/queue"
      |  aws.region = "eu-west-1"
      |  postgres {
      |    url = "jdbc:postgresql://db:5432/analytics"
      |    user = "u"
      |    password = "p"
      |    max-pool-size = 7
      |  }
      |}""".stripMargin

  "AppConfig.fromConfig" should "apply defaults for every optional key" in {
    val cfg = AppConfig.fromConfig(ConfigFactory.parseString(required))
    cfg.s3 shouldBe S3Config("lake")
    cfg.sqs shouldBe SqsConfig("http://sqs/queue")
    cfg.aws shouldBe AwsConfig("eu-west-1", None)
    cfg.postgres shouldBe PostgresConfig("jdbc:postgresql://db:5432/analytics", "u", "p", 7)
    cfg.repository shouldBe RepositoryConfig("postgres")
    cfg.repository.isPostgres shouldBe true
    cfg.server shouldBe ServerConfig("0.0.0.0", 8088)
  }

  it should "read optional endpoint, backend and server settings when present" in {
    val overrides =
      """analytics {
        |  aws.endpoint-url = "http://localstack:4566"
        |  repository.backend = "in-memory"
        |  server { host = "127.0.0.1", port = 9999 }
        |}""".stripMargin
    val cfg = AppConfig.fromConfig(ConfigFactory.parseString(overrides).withFallback(ConfigFactory.parseString(required)))
    cfg.aws.endpointUrl shouldBe Some("http://localstack:4566")
    cfg.repository.isPostgres shouldBe false
    cfg.server shouldBe ServerConfig("127.0.0.1", 9999)
  }

  it should "fail fast when a required key is missing" in {
    an[com.typesafe.config.ConfigException.Missing] should be thrownBy
      AppConfig.fromConfig(ConfigFactory.parseString("""analytics { s3.data-lake-bucket = "x" }"""))
  }

  "RepositoryConfig.isPostgres" should "be case- and whitespace-insensitive" in {
    RepositoryConfig(" PostgreS ").isPostgres shouldBe true
    RepositoryConfig("in-memory").isPostgres shouldBe false
    RepositoryConfig("").isPostgres shouldBe false
  }

  "AppConfig.load" should "read the application config from the classpath" in {
    val cfg = AppConfig.load()
    cfg.s3.dataLakeBucket shouldBe "test-data-lake"
    cfg.postgres.maxPoolSize shouldBe 2
  }
