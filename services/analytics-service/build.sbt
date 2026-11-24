val scala3Version = "3.4.0"

lazy val root = project
  .in(file("."))
  .settings(
    name := "analytics-service",
    version := "0.1.0",
    scalaVersion := scala3Version,
    // The HTTP server is the default entrypoint (`java -jar`). The batch job
    // (com.otterworks.analytics.batch.UsageRollupJob) is a second main class run
    // explicitly via `java -cp app.jar ...` (see the analytics-service CronJob).
    Compile / mainClass := Some("com.otterworks.analytics.Main"),
    assembly / mainClass := Some("com.otterworks.analytics.Main"),
    libraryDependencies ++= Seq(
      // Akka HTTP
      "com.typesafe.akka" %% "akka-http" % "10.5.3" cross CrossVersion.for3Use2_13,
      "com.typesafe.akka" %% "akka-actor-typed" % "2.8.8" cross CrossVersion.for3Use2_13,
      "com.typesafe.akka" %% "akka-stream" % "2.8.8" cross CrossVersion.for3Use2_13,
      "com.typesafe.akka" %% "akka-http-spray-json" % "10.5.3" cross CrossVersion.for3Use2_13,

      // JSON
      "io.circe" %% "circe-core" % "0.14.17",
      "io.circe" %% "circe-generic" % "0.14.17",
      "io.circe" %% "circe-parser" % "0.14.17",

      // Database - Slick for PostgreSQL
      "com.typesafe.slick" %% "slick" % "3.5.2" cross CrossVersion.for3Use2_13,
      "com.typesafe.slick" %% "slick-hikaricp" % "3.5.2" cross CrossVersion.for3Use2_13,
      "org.postgresql" % "postgresql" % "42.7.15",

      // Schema migrations (Flyway bundles PostgreSQL support in the 9.x line)
      "org.flywaydb" % "flyway-core" % "9.22.3",

      // AWS SDK
      "software.amazon.awssdk" % "s3" % "2.59.7",
      "software.amazon.awssdk" % "sqs" % "2.59.7",

      // Configuration
      "com.typesafe" % "config" % "1.4.10",

      // Logging
      "ch.qos.logback" % "logback-classic" % "1.5.38",
      "net.logstash.logback" % "logstash-logback-encoder" % "7.4",
      "org.slf4j" % "slf4j-api" % "2.0.17",

      // Metrics
      "io.prometheus" % "simpleclient" % "0.16.0",
      "io.prometheus" % "simpleclient_common" % "0.16.0",
      "io.prometheus" % "simpleclient_hotspot" % "0.16.0",

      // Testing
      "org.scalatest" %% "scalatest" % "3.2.20" % Test,
      "com.typesafe.akka" %% "akka-http-testkit" % "10.5.3" % Test cross CrossVersion.for3Use2_13,
      "com.typesafe.akka" %% "akka-stream-testkit" % "2.8.8" % Test cross CrossVersion.for3Use2_13,
      "com.typesafe.akka" %% "akka-actor-testkit-typed" % "2.8.8" % Test cross CrossVersion.for3Use2_13,

      // Integration testing against a real PostgreSQL (skipped when Docker is unavailable)
      "com.dimafeng" %% "testcontainers-scala-scalatest" % "0.41.8" % Test,
      "com.dimafeng" %% "testcontainers-scala-postgresql" % "0.41.8" % Test,
    ),
    dependencyOverrides ++= Seq(
      // logstash-logback-encoder 7.4 pulls jackson 2.15.2 (CVE-affected); pin the patched line.
      "com.fasterxml.jackson.core" % "jackson-core" % "2.21.8",
      "com.fasterxml.jackson.core" % "jackson-databind" % "2.21.8",
      "com.fasterxml.jackson.core" % "jackson-annotations" % "2.21",
      // testcontainers-java 1.20 speaks Docker API 1.32, which Docker 29+ rejects.
      "org.testcontainers" % "testcontainers" % "1.21.4" % Test,
      "org.testcontainers" % "postgresql" % "1.21.4" % Test,
      "org.testcontainers" % "jdbc" % "1.21.4" % Test,
      "org.testcontainers" % "database-commons" % "1.21.4" % Test,
      "org.apache.commons" % "commons-compress" % "1.28.0" % Test,
    ),
    assembly / assemblyMergeStrategy := {
      // Preserve ServiceLoader registrations (Flyway discovers its database
      // and plugin support via META-INF/services).
      case PathList("META-INF", "services", _*) => MergeStrategy.concat
      case PathList("META-INF", _*) => MergeStrategy.discard
      case "reference.conf" => MergeStrategy.concat
      case _ => MergeStrategy.first
    },
  )
