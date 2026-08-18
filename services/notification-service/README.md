# Notification Service

Kotlin 1.9 / Ktor service that consumes domain events from SQS (fanned out via
SNS), renders notification templates, and delivers notifications via email
(SES), in-app push, and webhooks. Notification history is stored in DynamoDB.

## Event types

The consumer handles the `EventType` enum
(`src/main/kotlin/com/otterworks/notification/model/NotificationEvent.kt`):

- `file_shared`
- `comment_added`
- `document_edited`
- `user_mentioned`
- `comment_resolved`

## Comment resolution notifications

When a comment thread is resolved in the document-service, it publishes a
`comment_resolved` SNS event:

```json
{
  "event_type": "comment_resolved",
  "timestamp": "<ISO-8601>",
  "payload": {
    "documentId": "<uuid>",
    "commentId": "<uuid>",
    "resolvedBy": "<uuid of resolving user>",
    "authorId": "<uuid of the comment's author>",
    "timestamp": "<ISO-8601>"
  }
}
```

The consumer maps this event to a "Your comment was resolved" template
(`NotificationTemplates.kt`) and notifies the comment's **author**
(`authorId`) — the resolver themselves is not notified.

## Development

- Build: Gradle (`build.gradle.kts`)
- Tests: `./gradlew test`
