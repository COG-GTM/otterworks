# Runbook: Notification Processing Failures

**Severity:** Critical

## Alert

`NotificationConsumerProcessingErrors` -- fires when the notification-service SQS consumer is generating sustained processing errors.

## Symptoms

- Users stop receiving notifications (email, in-app) for shared files and document updates.
- The Chaos Scenarios dashboard shows non-zero processing error rate on the notification-service panel.
- SQS queue depth grows unboundedly as failed messages re-enter after visibility timeout.

## Investigation Steps

1. Check notification-service consumer logs for deserialization errors:
   ```
   kubectl logs -l app=notification-service --tail=100 -n otterworks | grep -i "deseriali\|timestamp\|schema"
   ```
2. Check whether the chaos flag `chaos:notification-service:consumer_strict_schema` is set in Redis:
   ```
   redis-cli EXISTS chaos:notification-service:consumer_strict_schema
   ```

3. Inspect a failing message body (`Failed to parse message body` log line) and compare the
   `timestamp` field and any extra fields against `SqsNotificationMessage`. Older producers
   emit Unix epoch numbers for `timestamp`.

## Resolution Steps

- The consumer parses with `ignoreUnknownKeys`/`isLenient` and normalizes `timestamp` via
  `FlexibleTimestampSerializer`, which accepts RFC 3339 strings and epoch seconds/milliseconds.
  If a new producer format appears, extend that serializer rather than tightening the parser.
- Messages that still cannot be parsed are left undeleted and move to
  `otterworks-notifications-dlq` after 3 receives (`maxReceiveCount`). Once a fix is deployed,
  redrive them back to the main queue (`aws sqs start-message-move-task --source-arn <dlq-arn>`).

## Post-Incident

- Confirm `notifications_processing_errors_total` returns to zero and the DLQ depth is stable.
