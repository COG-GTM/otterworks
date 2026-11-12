plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ktor)
    alias(libs.plugins.shadow)
}

group = "com.otterworks"
version = "0.1.0"

application {
    mainClass.set("com.otterworks.notification.ApplicationKt")
}

repositories {
    mavenCentral()
}

// Dependency and plugin versions live in gradle/libs.versions.toml.
dependencies {
    // Ktor Server
    implementation(libs.ktor.server.core)
    implementation(libs.ktor.server.netty)
    implementation(libs.ktor.server.content.negotiation)
    implementation(libs.ktor.server.status.pages)
    implementation(libs.ktor.server.cors)
    implementation(libs.ktor.server.websockets)
    implementation(libs.ktor.server.call.logging)
    implementation(libs.ktor.server.default.headers)
    implementation(libs.ktor.server.metrics.micrometer)
    implementation(libs.ktor.serialization.kotlinx.json)

    // Ktor Client (for calling other services)
    implementation(libs.ktor.client.core)
    implementation(libs.ktor.client.cio)
    implementation(libs.ktor.client.content.negotiation)

    // AWS SDK for Kotlin
    implementation(libs.aws.sqs)
    implementation(libs.aws.sns)
    implementation(libs.aws.ses)
    implementation(libs.aws.dynamodb)

    // Notification template interpolation
    implementation(libs.commons.text)

    // Serialization
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.core)

    // Dependency Injection - Koin
    implementation(libs.koin.core)
    implementation(libs.koin.ktor)
    implementation(libs.koin.logger.slf4j)

    // Logging
    implementation(libs.logback.classic)
    implementation(libs.logstash.logback.encoder)
    implementation(libs.kotlin.logging.jvm)

    // Metrics & Tracing
    implementation(libs.micrometer.registry.prometheus)
    implementation(libs.opentelemetry.api)
    implementation(libs.opentelemetry.sdk)
    implementation(libs.opentelemetry.exporter.otlp)

    // Redis (chaos flag checks)
    implementation(libs.jedis)

    // Testing
    testImplementation(libs.ktor.server.tests)
    testImplementation(libs.ktor.server.test.host)
    testImplementation(libs.kotlin.test.junit)
    testImplementation(libs.mockk)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.koin.test)
}

kotlin {
    jvmToolchain(17)
}

tasks.withType<Test> {
    useJUnit()
    // Passthrough for the dependency transcript harness (security/deps); without these
    // properties the emitter test skips itself.
    listOf("ow.deps.cases", "ow.deps.observed").forEach { key ->
        System.getProperty(key)?.let { systemProperty(key, it) }
    }
}
