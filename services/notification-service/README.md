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

## Build and test

The repository CI command for this service is:

```bash
gradle check --no-daemon
```

On this machine, a machine-level Gradle init script strips the plugin portal.
Use the service's repository init script when running locally here:

```bash
gradle check --no-daemon -I gradle-init.gradle
```
