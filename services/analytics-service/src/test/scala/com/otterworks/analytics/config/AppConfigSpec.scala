package com.otterworks.analytics.config

import com.typesafe.config.{Config, ConfigException, ConfigFactory, ConfigResolveOptions}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.io.File
import scala.jdk.CollectionConverters.*

class AppConfigSpec extends AnyFlatSpec with Matchers:

  // The packaged config, resolved against a controlled environment instead of the real one.
  private def packagedConfig(env: Map[String, String]): Config =
    ConfigFactory
      .parseMap(env.asJava)
      .withFallback(ConfigFactory.parseFile(new File("src/main/resources/application.conf")))
      .resolve(ConfigResolveOptions.noSystem())

  "AppConfig" should "fail fast when no password is supplied for the postgres backend" in {
    val ex = intercept[ConfigException.Missing] {
      AppConfig.fromConfig(packagedConfig(Map.empty))
    }
    ex.getMessage should include("POSTGRES_PASSWORD")
  }

  it should "reject an empty password for the postgres backend" in {
    an[ConfigException.Missing] should be thrownBy
      AppConfig.fromConfig(packagedConfig(Map("POSTGRES_PASSWORD" -> "")))
  }

  it should "use POSTGRES_PASSWORD when set" in {
    val cfg = AppConfig.fromConfig(packagedConfig(Map("POSTGRES_PASSWORD" -> "from-env")))
    cfg.postgres.password shouldBe "from-env"
  }

  it should "prefer DATABASE_PASSWORD over POSTGRES_PASSWORD" in {
    val cfg = AppConfig.fromConfig(
      packagedConfig(Map("POSTGRES_PASSWORD" -> "compose", "DATABASE_PASSWORD" -> "deploy")))
    cfg.postgres.password shouldBe "deploy"
  }

  it should "not require a password for the in-memory backend" in {
    val cfg = AppConfig.fromConfig(packagedConfig(Map("ANALYTICS_REPOSITORY_BACKEND" -> "in-memory")))
    cfg.repository.isPostgres shouldBe false
    cfg.postgres.password shouldBe ""
  }
