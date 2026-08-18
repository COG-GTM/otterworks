# Notification Service

The notification service consumes notification events from SQS, including
messages delivered through an SNS fan-out, renders them for delivery, and
stores notification history in DynamoDB. It is a Kotlin 1.9 service built with
Ktor.

The service listens on port `8086`. The API gateway routes
`/api/v1/notifications` to it. Notification history and preferences are
persisted through the DynamoDB repository; WebSocket connections support in-app
delivery and SES supports email delivery.

## API surface

The main HTTP routes are:

- `GET /api/v1/notifications` — paginated notifications for a user.
- `GET /api/v1/notifications/unread-count` — unread count for a user.
- `GET /api/v1/notifications/{id}` — retrieve one notification.
- `PUT /api/v1/notifications/{id}/read` and
  `PUT /api/v1/notifications/read-all` — mark notifications as read.
- `DELETE /api/v1/notifications/{id}` — delete a notification.
- `/api/v1/preferences` — read and update delivery preferences.
- `/ws/notifications/{userId}` — WebSocket notification delivery.

The notification and preference routes obtain the user ID from the
`X-User-ID` header or the corresponding `user_id` query parameter.

## Supported events and routing

The consumer supports these event types:

`file_shared`, `comment_added`, `comment_resolved`, `document_edited`, and
`user_mentioned`.

For each event, the target user, resource metadata, and default delivery
channels are resolved as follows. The field names in this table are the fields
of the SQS notification message model.

| Event | Target user | Resource ID | Resource type | Default channels |
|---|---|---|---|---|
| `file_shared` | `sharedWithUserId` | `fileId` | `file` | `EMAIL` + `IN_APP` + `PUSH` |
| `comment_added` | `userId`, falling back to `ownerId` | `commentId`, falling back to `documentId` | `comment` | `IN_APP` + `PUSH` |
| `comment_resolved` | `userId`, falling back to `ownerId` | `commentId`, falling back to `documentId` | `comment` | `IN_APP` + `PUSH` |
| `document_edited` | `userId`, falling back to `ownerId` | `documentId` | `document` | `IN_APP` |
| `user_mentioned` | `mentionedUserId`, falling back to `userId` | `documentId` | `document` | `EMAIL` + `IN_APP` + `PUSH` |

The channels above are `NotificationPreference` defaults, resolved per event
type: a user's stored channels for that event type win, otherwise the default for
that event type applies, and an event type absent from both falls back to
`IN_APP`. Stored preferences for one event type therefore do not affect the
defaults used for another.

For `comment_resolved`, `userId` is the comment author. This keeps the
resolution notification targeted at the author rather than the document owner.

## Comment-resolved notification

The `comment_resolved` template has:

- title: `Comment Resolved`
- email subject: `OtterWorks: Your comment was resolved`

Its message identifies the resolver and document. When rendering this event,
the template renderer uses `actorId` when present. If `actorId` is empty, it
falls back to `resolvedBy`; if both are empty, it falls back to `ownerId`.

## Message intake

`SqsConsumer` first parses a bare `SqsNotificationMessage` body. If that fails,
it parses an SNS notification envelope and then parses the envelope's
`Message` field as the event body. Thus both direct SQS messages and
SNS-enveloped message bodies are accepted.

Both paths require a flat camelCase body with a top-level `eventType`. Events
published by document-service (`comment_added`, `comment_resolved`) instead use a
nested snake_case envelope (`{event_type, timestamp, payload}`), so they fail to
parse today — a pre-existing cross-service gap, not specific to
`comment_resolved`. search-service normalizes both shapes in
`app/services/sqs_consumer.py` and is the natural reference if the two sides are
aligned. Note that unwrapping the envelope alone is not sufficient: the payload
field names also differ (`author_id` vs. `userId`, `resolved_by` vs.
`resolvedBy`), so any alignment has to map field names too.

When the chaos flag `chaos:notification-service:consumer_strict_schema` is set,
intake switches to a strict JSON parser and messages fail to parse and stay in
the queue, so queue depth climbs while the consumer still looks healthy. That is
an intentional lab mechanism (see `AGENTS.md`). Note the strict parser sets
`ignoreUnknownKeys = false` and `isLenient = false`, so it rejects any body
carrying unknown fields — including every SNS envelope — and not only the legacy
integer timestamps its code comment describes.

## Build and test

The repository CI command for this service is:

```bash
gradle check --no-daemon
```

If a local Gradle init script strips the plugin portal, add the service's
repository init script:

```bash
gradle check --no-daemon -I gradle-init.gradle
```
