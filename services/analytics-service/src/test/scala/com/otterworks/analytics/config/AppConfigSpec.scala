package com.otterworks.analytics.config

import com.typesafe.config.{ConfigException, ConfigFactory, ConfigResolveOptions}
import org.scalatest.flatspec.AnyFlatSpec
import org.scalatest.matchers.should.Matchers

import java.io.File
import scala.jdk.CollectionConverters.*

class AppConfigSpec extends AnyFlatSpec with Matchers:

  private val packagedConf = new File("src/main/resources/application.conf")

  /** Loads the packaged application.conf, resolving `${?VAR}` against `env` instead of the real environment. */
  private def loadPackaged(env: Map[String, String]): AppConfig =
    require(packagedConf.isFile, s"${packagedConf.getAbsolutePath} not found")
    val resolved = ConfigFactory
      .parseFile(packagedConf)
      .withFallback(ConfigFactory.parseMap(env.asJava))
      .resolve(ConfigResolveOptions.defaults().setUseSystemEnvironment(false))
    AppConfig.fromConfig(resolved)

  "AppConfig" should "ship no default PostgreSQL password" in {
    val ex = the[ConfigException.BadValue] thrownBy loadPackaged(Map.empty)
    ex.getMessage should include("POSTGRES_PASSWORD")
    ex.getMessage should include("DATABASE_PASSWORD")
  }

  it should "reject an empty password for the postgres backend" in {
    a[ConfigException.BadValue] should be thrownBy loadPackaged(Map("POSTGRES_PASSWORD" -> ""))
  }

  it should "take the password from POSTGRES_PASSWORD" in {
    loadPackaged(Map("POSTGRES_PASSWORD" -> "from-compose")).postgres.password shouldBe "from-compose"
  }

  it should "prefer DATABASE_PASSWORD over POSTGRES_PASSWORD" in {
    val cfg = loadPackaged(Map("POSTGRES_PASSWORD" -> "compose", "DATABASE_PASSWORD" -> "deploy"))
    cfg.postgres.password shouldBe "deploy"
  }

  it should "not require a password for the in-memory backend" in {
    val cfg = loadPackaged(Map("ANALYTICS_REPOSITORY_BACKEND" -> "in-memory"))
    cfg.repository.isPostgres shouldBe false
    cfg.postgres.password shouldBe ""
  }
