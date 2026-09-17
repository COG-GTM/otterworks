output "notification_queue_url" {
  description = "SQS queue URL for notification events"
  value       = aws_sqs_queue.notifications.url
}

output "notification_queue_arn" {
  description = "SQS queue ARN for notification events"
  value       = aws_sqs_queue.notifications.arn
}

output "analytics_queue_url" {
  description = "SQS queue URL for analytics events"
  value       = aws_sqs_queue.analytics_events.url
}

output "analytics_queue_arn" {
  description = "SQS queue ARN for analytics events"
  value       = aws_sqs_queue.analytics_events.arn
}

output "search_indexing_queue_url" {
  description = "SQS queue URL for search indexing"
  value       = aws_sqs_queue.search_indexing.url
}

output "search_indexing_queue_arn" {
  description = "SQS queue ARN for search indexing"
  value       = aws_sqs_queue.search_indexing.arn
}

output "events_topic_arn" {
  description = "SNS topic ARN for system events"
  value       = aws_sns_topic.events.arn
}

output "events_kms_key_arn" {
  description = "ARN of the customer managed key encrypting the events topic"
  value       = aws_kms_key.events.arn
}
