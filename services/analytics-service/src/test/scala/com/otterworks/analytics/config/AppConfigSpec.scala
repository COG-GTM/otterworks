package com.otterworks.analytics.config

import com.typesafe.config.ConfigFactory
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

class AppConfigSpec extends AnyFlatSpec with Matchers:

  private def parse(extra: String): AppConfig =
    AppConfig.fromConfig(ConfigFactory.parseString(
      s"""analytics {
         |  s3.data-lake-bucket = "bucket"
         |  sqs.events-queue-url = "http://sqs.local/queue"
         |  aws.region = "eu-west-1"
         |  postgres {
         |    url = "jdbc:postgresql://db/analytics"
         |    user = "u"
         |    password = "p"
         |    max-pool-size = 4
         |  }
         |  $extra
         |}""".stripMargin))

  "AppConfig.fromConfig" should "apply the documented defaults when optional keys are absent" in {
    val cfg = parse("")
    cfg.server.host shouldBe "0.0.0.0"
    cfg.server.port shouldBe 8088
    cfg.repository.backend shouldBe "postgres"
    cfg.repository.isPostgres shouldBe true
    cfg.aws.endpointUrl shouldBe None
  }

  it should "prefer explicitly configured values over the defaults" in {
    val cfg = parse(
      """server { host = "127.0.0.1", port = 9099 }
        |repository.backend = "in-memory"
        |aws.endpoint-url = "http://localstack:4566"""".stripMargin)
    cfg.server.host shouldBe "127.0.0.1"
    cfg.server.port shouldBe 9099
    cfg.repository.backend shouldBe "in-memory"
    cfg.repository.isPostgres shouldBe false
    cfg.aws.endpointUrl shouldBe Some("http://localstack:4566")
  }

  it should "map the mandatory s3, sqs, aws and postgres sections" in {
    val cfg = parse("")
    cfg.s3.dataLakeBucket shouldBe "bucket"
    cfg.sqs.eventsQueueUrl shouldBe "http://sqs.local/queue"
    cfg.aws.region shouldBe "eu-west-1"
    cfg.postgres shouldBe PostgresConfig("jdbc:postgresql://db/analytics", "u", "p", 4)
  }

  it should "fail loudly when a mandatory key is missing" in {
    an[Exception] should be thrownBy
      AppConfig.fromConfig(ConfigFactory.parseString("""analytics { s3.data-lake-bucket = "b" }"""))
  }

  "AppConfig.load" should "read the packaged reference configuration" in {
    val cfg = AppConfig.load()
    // Not an exact port: MainSpec overrides analytics.server.port via a system property.
    cfg.server.port should be > 0
    cfg.s3.dataLakeBucket should not be empty
    cfg.sqs.eventsQueueUrl should startWith("http")
    cfg.postgres.maxPoolSize should be > 0
  }

  "RepositoryConfig.isPostgres" should "normalise case and surrounding whitespace" in {
    RepositoryConfig("  PostGres ").isPostgres shouldBe true
    RepositoryConfig("POSTGRES").isPostgres shouldBe true
    RepositoryConfig("in-memory").isPostgres shouldBe false
    RepositoryConfig("").isPostgres shouldBe false
  }
