# Notification Service

Kotlin 1.9 / Ktor 2.3 service that consumes domain events from SQS (including
SNS-wrapped messages), stores notification history in DynamoDB, and delivers
email, in-app, and push notifications.

## Consumed events

The consumer handles `file_shared`, `comment_added`, `comment_resolved`,
`document_edited`, and `user_mentioned`. A `comment_resolved` event targets the
comment author, uses the comment as its resource, and defaults to in-app and
push delivery.

HTTP routes provide notification listing, read state, and preference management;
see `src/main/kotlin/com/otterworks/notification/routes/Routes.kt` for the
complete route list. The service listens on port 8086 by default.

## Local development and tests

```bash
gradle run --no-daemon --init-script gradle-init.gradle
gradle test --no-daemon --init-script gradle-init.gradle
gradle build --no-daemon --init-script gradle-init.gradle
```
