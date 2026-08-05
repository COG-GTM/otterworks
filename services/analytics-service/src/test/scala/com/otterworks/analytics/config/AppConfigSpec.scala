package com.otterworks.analytics.config

import com.typesafe.config.{ConfigException, ConfigFactory}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

class AppConfigSpec extends AnyFlatSpec with Matchers:

  private def parse(extra: String): AppConfig =
    AppConfig.fromConfig(ConfigFactory.parseString(
      s"""analytics {
         |  s3.data-lake-bucket = "lake-bucket"
         |  sqs.events-queue-url = "http://sqs.local/queue"
         |  aws.region = "eu-west-1"
         |  postgres {
         |    url = "jdbc:postgresql://db/analytics"
         |    user = "svc"
         |    password = "secret"
         |    max-pool-size = 4
         |  }
         |  $extra
         |}""".stripMargin
    ))

  "AppConfig.fromConfig" should "read the mandatory S3, SQS, AWS and PostgreSQL settings" in {
    val cfg = parse("")
    cfg.s3.dataLakeBucket shouldBe "lake-bucket"
    cfg.sqs.eventsQueueUrl shouldBe "http://sqs.local/queue"
    cfg.aws.region shouldBe "eu-west-1"
    cfg.postgres shouldBe PostgresConfig("jdbc:postgresql://db/analytics", "svc", "secret", 4)
  }

  it should "apply the documented defaults when the optional keys are absent" in {
    val cfg = parse("")
    cfg.aws.endpointUrl shouldBe None
    cfg.repository.backend shouldBe "postgres"
    cfg.repository.isPostgres shouldBe true
    cfg.server shouldBe ServerConfig("0.0.0.0", 8088)
  }

  it should "prefer explicit values over the defaults" in {
    val cfg = parse(
      """server { host = "127.0.0.1", port = 9099 }
        |repository.backend = "in-memory"
        |aws.endpoint-url = "http://localstack:4566"""".stripMargin
    )
    cfg.server shouldBe ServerConfig("127.0.0.1", 9099)
    cfg.aws.endpointUrl shouldBe Some("http://localstack:4566")
    cfg.repository.backend shouldBe "in-memory"
    cfg.repository.isPostgres shouldBe false
  }

  it should "fail loudly when a mandatory key is missing" in {
    a[ConfigException.Missing] should be thrownBy
      AppConfig.fromConfig(ConfigFactory.parseString("""analytics { aws.region = "us-east-1" }"""))
  }

  "AppConfig.load" should "read the bundled application.conf" in {
    val cfg = AppConfig.load()
    cfg.server.port shouldBe 8088
    cfg.s3.dataLakeBucket shouldBe "test-data-lake"
    cfg.postgres.maxPoolSize shouldBe 2
    cfg.repository.isPostgres shouldBe false
  }

  "RepositoryConfig.isPostgres" should "normalise case and surrounding whitespace" in {
    RepositoryConfig("  PostGres ").isPostgres shouldBe true
    RepositoryConfig("postgres").isPostgres shouldBe true
    RepositoryConfig("in-memory").isPostgres shouldBe false
    RepositoryConfig("").isPostgres shouldBe false
  }
